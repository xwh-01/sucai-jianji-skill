import AppKit
import AVFoundation
import AVFAudio
import CoreText
import CoreVideo
import Foundation

enum RewindError: Error, CustomStringConvertible {
    case message(String)

    var description: String {
        switch self {
        case .message(let value): return value
        }
    }
}

struct Options {
    let input: URL
    let output: URL
    let insertTime: Double
    let sourceDuration: Double
    let sourcePosition: String
    let preFreezeDuration: Double
    let preCardDuration: Double
    let preCardText: String?
    let transitionDuration: Double
    let fpsOverride: Double?
    let soundLevel: Double
}

func usage() -> String {
    """
    Usage:
      insert_rewind_transition <input-video> <output-video> \\
        --at <seconds> [--source-duration <seconds>] \\
        [--source-position <before|after>] \\
        [--pre-freeze-duration <seconds>] \\
        [--pre-card-duration <seconds>] \\
        [--pre-card-text <line-1|line-2>] \\
        [--transition-duration <seconds>] [--fps <frames-per-second>] \\
        [--sound-level <0...1>]

    Defaults:
      source-duration=2.4, source-position=before,
      pre-freeze-duration=0, pre-card-duration=0,
      pre-card-text unset,
      transition-duration=0.4, fps=source frame duration,
      sound-level=0.72
    """
}

func parseOptions() throws -> Options {
    let arguments = CommandLine.arguments
    guard arguments.count >= 5 else {
        throw RewindError.message(usage())
    }

    let input = URL(fileURLWithPath: arguments[1]).standardizedFileURL
    let output = URL(fileURLWithPath: arguments[2]).standardizedFileURL
    var values: [String: String] = [:]
    var index = 3
    while index < arguments.count {
        let key = arguments[index]
        guard key.hasPrefix("--"), index + 1 < arguments.count else {
            throw RewindError.message("Invalid option near \(key)\n\(usage())")
        }
        values[key] = arguments[index + 1]
        index += 2
    }

    let preCardText = values["--pre-card-text"].flatMap {
        $0.isEmpty ? nil : $0.replacingOccurrences(of: "|", with: "\n")
    }
    let legacyHold = values["--pre-hold-duration"] ?? "0"
    let freezeDefault = preCardText == nil ? legacyHold : "0"
    let cardDefault = preCardText == nil ? "0" : legacyHold
    guard let insertTime = Double(values["--at"] ?? ""),
          let sourceDuration = Double(values["--source-duration"] ?? "2.4"),
          let preFreezeDuration = Double(values["--pre-freeze-duration"] ?? freezeDefault),
          let preCardDuration = Double(values["--pre-card-duration"] ?? cardDefault),
          let transitionDuration = Double(values["--transition-duration"] ?? "0.4"),
          let soundLevel = Double(values["--sound-level"] ?? "0.72"),
          insertTime > 0,
          sourceDuration > 0,
          preFreezeDuration >= 0,
          preCardDuration >= 0,
          transitionDuration > 0,
          (0...1).contains(soundLevel) else {
        throw RewindError.message("Invalid timing, fps, or sound level\n\(usage())")
    }
    let sourcePosition = values["--source-position"] ?? "before"
    if preCardDuration > 0, preCardText == nil {
        throw RewindError.message("--pre-card-text is required when --pre-card-duration is positive")
    }
    guard ["before", "after"].contains(sourcePosition) else {
        throw RewindError.message("--source-position must be before or after")
    }
    guard input != output else {
        throw RewindError.message("Input and output paths must be different")
    }

    return Options(
        input: input,
        output: output,
        insertTime: insertTime,
        sourceDuration: sourceDuration,
        sourcePosition: sourcePosition,
        preFreezeDuration: preFreezeDuration,
        preCardDuration: preCardDuration,
        preCardText: preCardText,
        transitionDuration: transitionDuration,
        fpsOverride: try values["--fps"].map {
            guard let value = Double($0), value > 0 else {
                throw RewindError.message("--fps must be a positive number")
            }
            return value
        },
        soundLevel: soundLevel
    )
}

func frameDuration(for track: AVAssetTrack, fpsOverride: Double?) async throws -> CMTime {
    if let fpsOverride {
        return CMTime(seconds: 1.0 / fpsOverride, preferredTimescale: 600_000)
    }
    let sourceDuration = try await track.load(.minFrameDuration)
    guard sourceDuration.isValid,
          !sourceDuration.isIndefinite,
          sourceDuration.value > 0,
          sourceDuration.timescale > 0 else {
        throw RewindError.message(
            "Source frame duration is unavailable; normalize VFR input with FFmpeg or pass --fps"
        )
    }
    return sourceDuration
}

func stagingURL(for output: URL) -> URL {
    let ext = output.pathExtension
    let stem = output.deletingPathExtension().lastPathComponent
    let filename = ".\(stem).\(UUID().uuidString).staging" + (ext.isEmpty ? "" : ".\(ext)")
    return output.deletingLastPathComponent().appendingPathComponent(filename)
}

func commitStagedOutput(_ staged: URL, to output: URL) throws {
    let manager = FileManager.default
    if manager.fileExists(atPath: output.path) {
        _ = try manager.replaceItemAt(output, withItemAt: staged)
    } else {
        try manager.moveItem(at: staged, to: output)
    }
}

func configuredFFmpeg() throws -> URL {
    guard let path = ProcessInfo.processInfo.environment["FFMPEG_PATH"],
          path.hasPrefix("/"),
          FileManager.default.isExecutableFile(atPath: path) else {
        throw RewindError.message("Set FFMPEG_PATH to the verified absolute FFmpeg executable path; PATH fallback is disabled")
    }
    return URL(fileURLWithPath: path)
}

func normalizeCFR(input: URL, output: URL, frameDuration: CMTime) throws {
    let process = Process()
    let errorPipe = Pipe()
    process.executableURL = try configuredFFmpeg()
    process.arguments = [
        "-hide_banner", "-loglevel", "error", "-y",
        "-i", input.path,
        "-map", "0:v:0", "-map", "0:a?",
        "-fps_mode", "cfr", "-r", "\(frameDuration.timescale)/\(frameDuration.value)",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", output.path
    ]
    process.standardError = errorPipe
    try process.run()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else {
        let data = errorPipe.fileHandleForReading.readDataToEndOfFile()
        let detail = String(data: data, encoding: .utf8) ?? "unknown FFmpeg error"
        throw RewindError.message("FFmpeg CFR normalization failed: \(detail)")
    }
}

func drawTitleCard(
    text: String,
    in context: CGContext,
    renderSize: CGSize
) {
    context.setFillColor(CGColor(gray: 0.015, alpha: 1))
    context.fill(CGRect(origin: .zero, size: renderSize))

    let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
    let firstLine = lines.first ?? text
    let secondLine = lines.dropFirst().joined(separator: " ")
    let centerX = renderSize.width / 2
    let centerY = renderSize.height / 2

    context.setFillColor(CGColor(red: 0.72, green: 0.57, blue: 0.30, alpha: 1))
    context.fill(CGRect(x: centerX - 32, y: centerY + 78, width: 64, height: 2))

    let availableWidth = renderSize.width * 0.86

    func drawLine(_ value: String, maxSize: CGFloat, baselineY: CGFloat, color: CGColor) {
        guard !value.isEmpty else { return }
        var fontSize = maxSize
        var line: CTLine
        var width: CGFloat
        repeat {
            let font = CTFontCreateWithName(
                "AvenirNextCondensed-DemiBold" as CFString,
                fontSize,
                nil
            )
            let attributes: [NSAttributedString.Key: Any] = [
                NSAttributedString.Key(kCTFontAttributeName as String): font,
                NSAttributedString.Key(kCTForegroundColorAttributeName as String): color,
                NSAttributedString.Key(kCTKernAttributeName as String): min(1.2, fontSize * 0.025)
            ]
            line = CTLineCreateWithAttributedString(
                NSAttributedString(string: value, attributes: attributes)
            )
            width = CGFloat(CTLineGetTypographicBounds(line, nil, nil, nil))
            if width > availableWidth {
                fontSize *= max(0.72, availableWidth / width * 0.98)
            }
        } while width > availableWidth && fontSize > 6
        context.textPosition = CGPoint(x: centerX - width / 2, y: baselineY)
        CTLineDraw(line, context)
    }

    drawLine(
        firstLine,
        maxSize: min(38, renderSize.width * 0.094),
        baselineY: centerY + 19,
        color: CGColor(gray: 0.78, alpha: 1)
    )
    drawLine(
        secondLine,
        maxSize: min(56, renderSize.width * 0.139),
        baselineY: centerY - 52,
        color: CGColor(gray: 0.98, alpha: 1)
    )
}

func makeHoldVideo(
    asset: AVURLAsset,
    sampleTime: Double,
    duration: Double,
    frameDuration: CMTime,
    renderSize: CGSize,
    titleCardText: String?,
    output: URL
) async throws {
    try? FileManager.default.removeItem(at: output)
    let writer = try AVAssetWriter(outputURL: output, fileType: .mov)
    let width = Int(renderSize.width)
    let height = Int(renderSize.height)
    let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
        AVVideoCodecKey: AVVideoCodecType.h264,
        AVVideoWidthKey: width,
        AVVideoHeightKey: height
    ])
    let attributes: [String: Any] = [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        kCVPixelBufferWidthKey as String: width,
        kCVPixelBufferHeightKey as String: height
    ]
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(
        assetWriterInput: input,
        sourcePixelBufferAttributes: attributes
    )
    guard writer.canAdd(input) else {
        throw RewindError.message("Cannot add hold video writer input")
    }
    writer.add(input)
    guard writer.startWriting() else {
        throw writer.error ?? RewindError.message("Cannot start hold video writer")
    }
    writer.startSession(atSourceTime: .zero)

    let image: CGImage?
    if titleCardText == nil {
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = false
        generator.requestedTimeToleranceBefore = CMTime(seconds: 1.0 / 120.0, preferredTimescale: 600)
        generator.requestedTimeToleranceAfter = CMTime(seconds: 1.0 / 120.0, preferredTimescale: 600)
        image = try generator.copyCGImage(
            at: CMTime(seconds: sampleTime, preferredTimescale: 600),
            actualTime: nil
        )
    } else {
        image = nil
    }
    let frameSeconds = frameDuration.seconds
    let frameCount = max(1, Int((duration / frameSeconds).rounded()))
    for frameIndex in 0..<frameCount {
        while !input.isReadyForMoreMediaData {
            try await Task.sleep(for: .milliseconds(2))
        }
        var optionalBuffer: CVPixelBuffer?
        CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_32BGRA,
            attributes as CFDictionary,
            &optionalBuffer
        )
        guard let buffer = optionalBuffer else {
            throw RewindError.message("Cannot allocate hold frame")
        }
        CVPixelBufferLockBaseAddress(buffer, [])
        guard let context = CGContext(
            data: CVPixelBufferGetBaseAddress(buffer),
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue
                | CGBitmapInfo.byteOrder32Little.rawValue
        ) else {
            CVPixelBufferUnlockBaseAddress(buffer, [])
            throw RewindError.message("Cannot create hold frame context")
        }
        if let titleCardText {
            drawTitleCard(text: titleCardText, in: context, renderSize: renderSize)
        } else if let image {
            context.draw(image, in: CGRect(origin: .zero, size: renderSize))
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])
        guard adaptor.append(
            buffer,
            withPresentationTime: CMTimeMultiply(frameDuration, multiplier: Int32(frameIndex))
        ) else {
            throw writer.error ?? RewindError.message("Cannot append hold frame")
        }
    }
    input.markAsFinished()
    await writer.finishWriting()
    guard writer.status == .completed else {
        throw writer.error ?? RewindError.message("Hold video writer failed")
    }
}

func evenDimension(_ value: CGFloat) -> Int {
    let rounded = max(2, Int(value.rounded()))
    return rounded.isMultiple(of: 2) ? rounded : rounded + 1
}

func normalizedTransform(for track: AVAssetTrack) async throws -> (CGAffineTransform, CGSize) {
    let naturalSize = try await track.load(.naturalSize)
    let preferredTransform = try await track.load(.preferredTransform)
    let width = evenDimension(abs(naturalSize.width))
    let height = evenDimension(abs(naturalSize.height))
    return (preferredTransform, CGSize(width: width, height: height))
}

func makeReverseVideo(
    asset: AVURLAsset,
    insertTime: Double,
    sourceDuration: Double,
    sourcePosition: String,
    assetDuration: Double,
    transitionDuration: Double,
    frameDuration: CMTime,
    renderSize: CGSize,
    output: URL
) async throws {
    try? FileManager.default.removeItem(at: output)
    let writer = try AVAssetWriter(outputURL: output, fileType: .mov)
    let width = Int(renderSize.width)
    let height = Int(renderSize.height)
    let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
        AVVideoCodecKey: AVVideoCodecType.h264,
        AVVideoWidthKey: width,
        AVVideoHeightKey: height,
        AVVideoCompressionPropertiesKey: [
            AVVideoAverageBitRateKey: width >= 1000 ? 3_000_000 : 1_800_000
        ]
    ])
    let attributes: [String: Any] = [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        kCVPixelBufferWidthKey as String: width,
        kCVPixelBufferHeightKey as String: height
    ]
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(
        assetWriterInput: input,
        sourcePixelBufferAttributes: attributes
    )
    guard writer.canAdd(input) else {
        throw RewindError.message("Cannot add reverse video writer input")
    }
    writer.add(input)
    guard writer.startWriting() else {
        throw writer.error ?? RewindError.message("Cannot start reverse video writer")
    }
    writer.startSession(atSourceTime: .zero)

    let generator = AVAssetImageGenerator(asset: asset)
    generator.appliesPreferredTrackTransform = false
    generator.requestedTimeToleranceBefore = CMTime(seconds: 1.0 / 120.0, preferredTimescale: 600)
    generator.requestedTimeToleranceAfter = CMTime(seconds: 1.0 / 120.0, preferredTimescale: 600)

    let frameSeconds = frameDuration.seconds
    let frameCount = max(2, Int((transitionDuration / frameSeconds).rounded()))
    let sourceStart: Double
    let sourceEnd: Double
    if sourcePosition == "after" {
        sourceStart = insertTime
        sourceEnd = min(
            assetDuration - frameSeconds,
            insertTime + sourceDuration - frameSeconds
        )
    } else {
        sourceEnd = max(0, insertTime - frameSeconds)
        sourceStart = max(0, insertTime - sourceDuration)
    }
    guard sourceEnd > sourceStart else {
        throw RewindError.message("The selected rewind source window is empty")
    }
    let sourceSpan = max(sourceEnd - sourceStart, 0.001)

    for frameIndex in 0..<frameCount {
        while !input.isReadyForMoreMediaData {
            try await Task.sleep(for: .milliseconds(2))
        }
        let progress = Double(frameIndex) / Double(frameCount - 1)
        let samplingProgress: Double
        if sourcePosition == "after" {
            if progress <= 0.75 {
                samplingProgress = progress * (0.85 / 0.75)
            } else {
                let landingProgress = (progress - 0.75) / 0.25
                let easedLanding = 1 - pow(1 - landingProgress, 2)
                samplingProgress = 0.85 + 0.15 * easedLanding
            }
        } else {
            samplingProgress = progress
        }
        let sourceSeconds = sourceEnd - sourceSpan * samplingProgress
        let image = try generator.copyCGImage(
            at: CMTime(seconds: sourceSeconds, preferredTimescale: 600),
            actualTime: nil
        )

        var optionalBuffer: CVPixelBuffer?
        CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_32BGRA,
            attributes as CFDictionary,
            &optionalBuffer
        )
        guard let buffer = optionalBuffer else {
            throw RewindError.message("Cannot allocate reverse frame")
        }
        CVPixelBufferLockBaseAddress(buffer, [])
        guard let context = CGContext(
            data: CVPixelBufferGetBaseAddress(buffer),
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue
                | CGBitmapInfo.byteOrder32Little.rawValue
        ) else {
            CVPixelBufferUnlockBaseAddress(buffer, [])
            throw RewindError.message("Cannot create reverse frame context")
        }
        context.draw(image, in: CGRect(origin: .zero, size: renderSize))
        CVPixelBufferUnlockBaseAddress(buffer, [])

        let presentationTime = CMTimeMultiply(frameDuration, multiplier: Int32(frameIndex))
        guard adaptor.append(buffer, withPresentationTime: presentationTime) else {
            throw writer.error ?? RewindError.message("Cannot append reverse frame")
        }
    }

    input.markAsFinished()
    await writer.finishWriting()
    guard writer.status == .completed else {
        throw writer.error ?? RewindError.message("Reverse video writer failed")
    }
}

func makeRewindSound(duration: Double, level: Double, output: URL) throws {
    try? FileManager.default.removeItem(at: output)
    let sampleRate = 48_000.0
    guard let format = AVAudioFormat(
        standardFormatWithSampleRate: sampleRate,
        channels: 2
    ) else {
        throw RewindError.message("Cannot create rewind audio format")
    }
    let frameCount = AVAudioFrameCount((duration * sampleRate).rounded())
    guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount),
          let channels = buffer.floatChannelData else {
        throw RewindError.message("Cannot allocate rewind audio buffer")
    }
    buffer.frameLength = frameCount

    var phase = 0.0
    var seed: UInt64 = 0x8f3d_27a1_4b9c_650d
    var previousNoise = 0.0
    for frame in 0..<Int(frameCount) {
        let progress = Double(frame) / Double(max(Int(frameCount) - 1, 1))
        let envelope = pow(max(0, sin(Double.pi * progress)), 0.72)
        let frequency = 260 + 2_250 * pow(progress, 1.7)
        phase += 2 * Double.pi * frequency / sampleRate
        seed = seed &* 6_364_136_223_846_793_005 &+ 1
        let unitNoise = Double((seed >> 33) & 0x7fff_ffff) / Double(0x7fff_ffff)
        let noise = unitNoise * 2 - 1
        let highNoise = noise - previousNoise * 0.82
        previousNoise = noise
        let tonal = 0.56 * sin(phase) + 0.22 * sin(phase * 1.93)
        let sample = Float(level * envelope * (0.34 * tonal + 0.16 * highNoise))
        channels[0][frame] = sample
        channels[1][frame] = sample
    }

    let file = try AVAudioFile(forWriting: output, settings: format.settings)
    try file.write(from: buffer)
}

@main struct Main {
    static func main() async throws {
        let options = try parseOptions()
        _ = try configuredFFmpeg()
        let asset = AVURLAsset(url: options.input)
        let duration = try await asset.load(.duration).seconds
        guard duration.isFinite, options.insertTime < duration else {
            throw RewindError.message("--at must fall inside the input video")
        }
        guard let sourceVideo = try await asset.loadTracks(withMediaType: .video).first else {
            throw RewindError.message("Input has no video track")
        }
        let sourceFrameDuration = try await frameDuration(
            for: sourceVideo,
            fpsOverride: options.fpsOverride
        )
        let frameSeconds = sourceFrameDuration.seconds
        let sourceAudio = try await asset.loadTracks(withMediaType: .audio).first
        let (sourceTransform, renderSize) = try await normalizedTransform(for: sourceVideo)

        try FileManager.default.createDirectory(
            at: options.output.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let workDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("rewind-transition-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: workDirectory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: workDirectory) }

        let reverseURL = workDirectory.appendingPathComponent("reverse.mov")
        let freezeURL = workDirectory.appendingPathComponent("freeze.mov")
        let cardURL = workDirectory.appendingPathComponent("card.mov")
        let soundURL = workDirectory.appendingPathComponent("rewind.caf")
        if options.preFreezeDuration > 0 {
            try await makeHoldVideo(
                asset: asset,
                sampleTime: max(0, options.insertTime - frameSeconds),
                duration: options.preFreezeDuration,
                frameDuration: sourceFrameDuration,
                renderSize: renderSize,
                titleCardText: nil,
                output: freezeURL
            )
        }
        if options.preCardDuration > 0 {
            try await makeHoldVideo(
                asset: asset,
                sampleTime: max(0, options.insertTime - frameSeconds),
                duration: options.preCardDuration,
                frameDuration: sourceFrameDuration,
                renderSize: renderSize,
                titleCardText: options.preCardText,
                output: cardURL
            )
        }
        try await makeReverseVideo(
            asset: asset,
            insertTime: options.insertTime,
            sourceDuration: options.sourceDuration,
            sourcePosition: options.sourcePosition,
            assetDuration: duration,
            transitionDuration: options.transitionDuration,
            frameDuration: sourceFrameDuration,
            renderSize: renderSize,
            output: reverseURL
        )
        try makeRewindSound(
            duration: options.transitionDuration,
            level: options.soundLevel,
            output: soundURL
        )

        let reverseAsset = AVURLAsset(url: reverseURL)
        let soundAsset = AVURLAsset(url: soundURL)
        let freezeAsset = options.preFreezeDuration > 0 ? AVURLAsset(url: freezeURL) : nil
        let cardAsset = options.preCardDuration > 0 ? AVURLAsset(url: cardURL) : nil
        guard let reverseVideo = try await reverseAsset.loadTracks(withMediaType: .video).first,
              let rewindAudio = try await soundAsset.loadTracks(withMediaType: .audio).first else {
            throw RewindError.message("Cannot load generated transition tracks")
        }
        let composition = AVMutableComposition()
        guard let videoTrack = composition.addMutableTrack(
            withMediaType: .video,
            preferredTrackID: kCMPersistentTrackID_Invalid
        ), let sourceAudioTrack = composition.addMutableTrack(
            withMediaType: .audio,
            preferredTrackID: kCMPersistentTrackID_Invalid
        ), let rewindAudioTrack = composition.addMutableTrack(
            withMediaType: .audio,
            preferredTrackID: kCMPersistentTrackID_Invalid
        ) else {
            throw RewindError.message("Cannot create composition tracks")
        }

        let insert = CMTime(seconds: options.insertTime, preferredTimescale: 600)
        let freeze = CMTime(seconds: options.preFreezeDuration, preferredTimescale: 600)
        let card = CMTime(seconds: options.preCardDuration, preferredTimescale: 600)
        let preTransition = freeze + card
        let transition = CMTime(seconds: options.transitionDuration, preferredTimescale: 600)
        let assetDuration = CMTime(seconds: duration, preferredTimescale: 600)
        let resumeSourceTime = options.sourcePosition == "after"
            ? insert + sourceFrameDuration
            : insert
        let outputDuration = assetDuration + preTransition + transition - (resumeSourceTime - insert)
        let beforeRange = CMTimeRange(start: .zero, duration: insert)
        let afterRange = CMTimeRange(
            start: resumeSourceTime,
            duration: assetDuration - resumeSourceTime
        )

        videoTrack.preferredTransform = sourceTransform
        try videoTrack.insertTimeRange(beforeRange, of: sourceVideo, at: .zero)
        if let freezeAsset,
           let freezeVideo = try await freezeAsset.loadTracks(withMediaType: .video).first {
            try videoTrack.insertTimeRange(
                CMTimeRange(start: .zero, duration: freeze),
                of: freezeVideo,
                at: insert
            )
        }
        if let cardAsset,
           let cardVideo = try await cardAsset.loadTracks(withMediaType: .video).first {
            try videoTrack.insertTimeRange(
                CMTimeRange(start: .zero, duration: card),
                of: cardVideo,
                at: insert + freeze
            )
        }
        try videoTrack.insertTimeRange(
            CMTimeRange(start: .zero, duration: transition),
            of: reverseVideo,
            at: insert + preTransition
        )
        try videoTrack.insertTimeRange(
            afterRange,
            of: sourceVideo,
            at: insert + preTransition + transition
        )

        if let sourceAudio {
            let audioDuration = try await sourceAudio.load(.timeRange).end
            let audioBeforeDuration = CMTimeMinimum(insert, audioDuration)
            if audioBeforeDuration > .zero {
                try sourceAudioTrack.insertTimeRange(
                    CMTimeRange(start: .zero, duration: audioBeforeDuration),
                    of: sourceAudio,
                    at: .zero
                )
            }
            let usableAudioEnd = CMTimeMinimum(audioDuration, assetDuration)
            if usableAudioEnd > resumeSourceTime {
                try sourceAudioTrack.insertTimeRange(
                    CMTimeRange(
                        start: resumeSourceTime,
                        duration: usableAudioEnd - resumeSourceTime
                    ),
                    of: sourceAudio,
                    at: insert + preTransition + transition
                )
            }
        }
        try rewindAudioTrack.insertTimeRange(
            CMTimeRange(start: .zero, duration: transition),
            of: rewindAudio,
            at: insert + preTransition
        )

        let audioMix = AVMutableAudioMix()
        let sourceAudioParameters = AVMutableAudioMixInputParameters(
            track: sourceAudioTrack
        )
        sourceAudioParameters.setVolume(1, at: .zero)
        let fadeDuration = CMTime(seconds: 0.08, preferredTimescale: 600)
        if insert > fadeDuration {
            sourceAudioParameters.setVolumeRamp(
                fromStartVolume: 1,
                toEndVolume: 0,
                timeRange: CMTimeRange(
                    start: insert - fadeDuration,
                    duration: fadeDuration
                )
            )
        }
        let resumeTimelineTime = insert + preTransition + transition
        sourceAudioParameters.setVolume(0, at: resumeTimelineTime)
        sourceAudioParameters.setVolumeRamp(
            fromStartVolume: 0,
            toEndVolume: 1,
            timeRange: CMTimeRange(
                start: resumeTimelineTime,
                duration: fadeDuration
            )
        )
        audioMix.inputParameters = [sourceAudioParameters]

        let compatibleOutput = options.output.pathExtension.lowercased() == "m4v"
        let preset = compatibleOutput
            ? AVAssetExportPresetAppleM4V720pHD
            : AVAssetExportPresetHighestQuality
        guard let exporter = AVAssetExportSession(asset: composition, presetName: preset) else {
            throw RewindError.message("Cannot create final exporter")
        }
        let videoComposition = AVMutableVideoComposition(propertiesOf: composition)
        videoComposition.frameDuration = sourceFrameDuration
        let avStagedOutput = stagingURL(for: options.output)
        let finalStagedOutput = stagingURL(for: options.output)
        defer {
            try? FileManager.default.removeItem(at: avStagedOutput)
            try? FileManager.default.removeItem(at: finalStagedOutput)
        }
        exporter.outputURL = avStagedOutput
        exporter.outputFileType = compatibleOutput ? .m4v : .mp4
        exporter.timeRange = CMTimeRange(
            start: .zero,
            duration: outputDuration
        )
        exporter.audioMix = audioMix
        exporter.videoComposition = videoComposition
        await exporter.export()
        guard exporter.status == .completed else {
            throw exporter.error ?? RewindError.message("Final export failed")
        }
        try normalizeCFR(
            input: avStagedOutput,
            output: finalStagedOutput,
            frameDuration: sourceFrameDuration
        )
        try commitStagedOutput(finalStagedOutput, to: options.output)

        print("output=\(options.output.path)")
        print("insert_time=\(String(format: "%.3f", options.insertTime))")
        print("rewind_source_duration=\(String(format: "%.3f", options.sourceDuration))")
        print("rewind_source_position=\(options.sourcePosition)")
        print("pre_freeze_duration=\(String(format: "%.3f", options.preFreezeDuration))")
        print("pre_card_duration=\(String(format: "%.3f", options.preCardDuration))")
        print("pre_card_text=\(options.preCardText ?? "none")")
        print("rewind_transition_duration=\(String(format: "%.3f", options.transitionDuration))")
        print("frame_duration=\(sourceFrameDuration.value)/\(sourceFrameDuration.timescale)")
        print("fps=\(String(format: "%.6f", 1.0 / frameSeconds))")
        print("output_duration=\(String(format: "%.3f", outputDuration.seconds))")
    }
}
