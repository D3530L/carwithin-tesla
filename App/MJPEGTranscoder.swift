import Foundation
import AVFoundation
import VideoToolbox
import CoreImage
import QuartzCore
import ImageIO
import CoreGraphics

/// Decodes CarPlay H.264/H.265 access units into JPEG frames for browsers that have neither
/// MediaSource nor WebCodecs (head units, e.g. the Tesla browser). Runs on the caller's queue:
/// `submit` must be called from the video-output queue, and `onJPEG` is invoked on the
/// decompression session's own thread, so the caller hops back before touching sockets.
final class MJPEGTranscoder {
    var onJPEG: ((Data, Int, Int) -> Void)?
    var onLog: ((String) -> Void)?

    private let targetFPS: Double
    private let maximumWidth: Int
    private let quality: CGFloat
    private let context = CIContext(options: [.cacheIntermediates: false])

    private var parameters = VideoParameterSets(codec: .h264)
    private var format: CMVideoFormatDescription?
    private var session: VTDecompressionSession?
    private var lastSubmitted: CFTimeInterval = 0
    private var width = 0
    private var height = 0
    private var framesIn = 0
    private var framesOut = 0

    init(targetFPS: Double = 15, maximumWidth: Int = 1280, quality: CGFloat = 0.55) {
        self.targetFPS = max(1, targetFPS)
        self.maximumWidth = max(160, maximumWidth)
        self.quality = min(max(quality, 0.1), 0.95)
    }

    deinit { teardown() }

    /// Drops parameter sets, format and decoder; the next keyframe rebuilds them.
    func reset() {
        teardown()
        parameters = VideoParameterSets(codec: .h264)
        framesIn = 0; framesOut = 0
    }

    var statistics: String { "\(framesOut)/\(framesIn) 帧 · \(width)×\(height)" }

    private func teardown() {
        if let session { VTDecompressionSessionInvalidate(session) }
        session = nil; format = nil
    }

    func submit(accessUnit: Data, codec: VideoCodec) {
        guard !accessUnit.isEmpty else { return }
        let units: [Data]
        do { units = try AnnexB.units(in: accessUnit) }
        catch { return }

        if parameters.codec != codec {
            teardown()
            parameters = VideoParameterSets(codec: codec)
        }
        var picture: [Data] = []
        var changed = false
        for unit in units {
            if codec.parameterSet(unit) != nil { if parameters.absorb(unit) { changed = true } }
            else { picture.append(unit) }
        }
        if (changed || format == nil), parameters.isComplete {
            do {
                let newFormat = try makeFormat()
                teardown()
                format = newFormat
                try makeSession(newFormat)
                onLog?("MJPEG 使用 \(codec.displayName)（\(parameters.summary)）")
            } catch {
                onLog?("MJPEG 解码器初始化失败：\(error.localizedDescription)")
                return
            }
        }
        guard !picture.isEmpty, let format, let session else { return }
        let keyframe = picture.contains { codec.isRandomAccess($0) }

        // Wall-clock pacing: JPEG is far heavier than the H.264 stream, so the head unit gets a
        // lower frame rate instead of a backlog it can never render. Keyframes always pass, or
        // the decoder would wait forever for one.
        let now = CACurrentMediaTime()
        guard keyframe || now - lastSubmitted >= 1.0 / targetFPS else { return }
        lastSubmitted = now
        framesIn += 1

        let bytes: Data
        do { bytes = try AnnexB.lengthPrefixed(picture) } catch { return }
        guard let sample = try? makeSample(bytes, format: format, keyframe: keyframe) else { return }
        var flagsOut = VTDecodeInfoFlags()
        let status = VTDecompressionSessionDecodeFrame(
            session, sampleBuffer: sample,
            flags: [._EnableAsynchronousDecompression], frameRefcon: nil, infoFlagsOut: &flagsOut)
        if status != noErr {
            // A decode error invalidates the session; rebuild on the next keyframe.
            teardown()
            onLog?("MJPEG 解码失败（\(status)），等待下一个关键帧")
        }
    }

    private func makeFormat() throws -> CMVideoFormatDescription {
        let units = parameters.ordered.map { $0 as NSData }
        let pointers = units.map { $0.bytes.assumingMemoryBound(to: UInt8.self) }
        let sizes = units.map(\.length)
        var description: CMVideoFormatDescription?
        let status: OSStatus
        switch parameters.codec {
        case .h264:
            status = CMVideoFormatDescriptionCreateFromH264ParameterSets(allocator: kCFAllocatorDefault,
                parameterSetCount: pointers.count, parameterSetPointers: pointers, parameterSetSizes: sizes,
                nalUnitHeaderLength: 4, formatDescriptionOut: &description)
        case .h265:
            status = CMVideoFormatDescriptionCreateFromHEVCParameterSets(allocator: kCFAllocatorDefault,
                parameterSetCount: pointers.count, parameterSetPointers: pointers, parameterSetSizes: sizes,
                nalUnitHeaderLength: 4, extensions: nil, formatDescriptionOut: &description)
        }
        guard status == noErr, let description else {
            throw ProtocolError.malformed("\(parameters.codec.displayName) 参数无效（\(status)）")
        }
        return description
    }

    private func makeSession(_ format: CMVideoFormatDescription) throws {
        let attributes: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferIOSurfacePropertiesKey as String: [String: Any](),
        ]
        var callback = VTDecompressionOutputCallbackRecord(
            decompressionOutputCallback: { refcon, _, status, _, imageBuffer, _, _ in
                guard status == noErr, let refcon, let imageBuffer else { return }
                Unmanaged<MJPEGTranscoder>.fromOpaque(refcon).takeUnretainedValue()
                    .makeJPEG(from: imageBuffer)
            },
            decompressionOutputRefCon: Unmanaged.passUnretained(self).toOpaque())
        var created: VTDecompressionSession?
        let status = VTDecompressionSessionCreate(allocator: kCFAllocatorDefault,
            formatDescription: format, decoderSpecification: nil,
            imageBufferAttributes: attributes as CFDictionary,
            outputCallback: &callback, decompressionSessionOut: &created)
        guard status == noErr, let created else {
            throw ProtocolError.malformed("无法创建解码会话（\(status)）")
        }
        session = created
        let dimensions = CMVideoFormatDescriptionGetDimensions(format)
        let scale = min(1.0, Double(maximumWidth) / Double(max(dimensions.width, 1)))
        width = Int(Double(dimensions.width) * scale) & ~1
        height = Int(Double(dimensions.height) * scale) & ~1
    }

    private func makeSample(_ lengthPrefixed: Data, format: CMVideoFormatDescription,
                           keyframe: Bool) throws -> CMSampleBuffer {
        var block: CMBlockBuffer?
        var status = CMBlockBufferCreateWithMemoryBlock(allocator: kCFAllocatorDefault, memoryBlock: nil,
            blockLength: lengthPrefixed.count, blockAllocator: kCFAllocatorDefault, customBlockSource: nil,
            offsetToData: 0, dataLength: lengthPrefixed.count, flags: 0, blockBufferOut: &block)
        guard status == noErr, let block else { throw ProtocolError.malformed("无法分配 MJPEG 缓冲区") }
        status = lengthPrefixed.withUnsafeBytes {
            CMBlockBufferReplaceDataBytes(with: $0.baseAddress!, blockBuffer: block,
                                          offsetIntoDestination: 0, dataLength: lengthPrefixed.count)
        }
        guard status == noErr else { throw ProtocolError.malformed("无法写入 MJPEG 缓冲区") }
        var sample: CMSampleBuffer?
        var size = lengthPrefixed.count
        var timing = CMSampleTimingInfo(duration: .invalid,
            presentationTimeStamp: CMClockGetTime(CMClockGetHostTimeClock()), decodeTimeStamp: .invalid)
        status = CMSampleBufferCreateReady(allocator: kCFAllocatorDefault, dataBuffer: block,
            formatDescription: format, sampleCount: 1, sampleTimingEntryCount: 1, sampleTimingArray: &timing,
            sampleSizeEntryCount: 1, sampleSizeArray: &size, sampleBufferOut: &sample)
        guard status == noErr, let sample else { throw ProtocolError.malformed("无法创建 MJPEG 帧") }
        if !keyframe, let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: true) as? [NSMutableDictionary] {
            attachments.first?[kCMSampleAttachmentKey_NotSync] = true
        }
        return sample
    }

    /// Called on the decompression session's thread.
    private func makeJPEG(from pixelBuffer: CVPixelBuffer) {
        var image = CIImage(cvPixelBuffer: pixelBuffer)
        let sourceWidth = CVPixelBufferGetWidth(pixelBuffer)
        if sourceWidth > maximumWidth {
            let scale = CGFloat(maximumWidth) / CGFloat(sourceWidth)
            image = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        }
        let extent = image.extent.integral
        guard extent.width >= 16, extent.height >= 16,
              let cgImage = context.createCGImage(image, from: extent) else { return }
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, "public.jpeg" as CFString, 1, nil) else { return }
        CGImageDestinationAddImage(destination, cgImage,
            [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { return }
        framesOut += 1
        onJPEG?(output as Data, cgImage.width, cgImage.height)
    }
}
