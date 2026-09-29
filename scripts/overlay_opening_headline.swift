import AppKit
import AVFoundation
import CoreText
import Foundation
import QuartzCore

enum HeadlineError: Error, CustomStringConvertible {
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
    let holdDuration: Double
    let fadeDuration: Double
    let lines: [String]
    let baseColor: CGColor
    let accentColor: CGColor
    let baseColorHex: String
    let accentColorHex: String
}

func usage() -> String {
    """
    Usage:
      overlay_opening_headline <input-video> <output-video> \\
        --hold-duration <seconds> --fade-duration <seconds> \\
        --line1 <text> --line2 <text> --line3 <text> \\
        --base-color <#RRGGBB> --accent-color <#RRGGBB>
    """
}

func parseHexColor(_ value: String, option: String) throws -> CGColor {
    let normalized = value.hasPrefix("#") ? String(value.dropFirst()) : value
    guard normalized.count == 6,
          let rgb = UInt32(normalized, radix: 16) else {
        throw HeadlineError.message("\(option) must be a six-digit RGB hex color")
    }
    return CGColor(
        red: CGFloat((rgb >> 16) & 0xFF) / 255,
        green: CGFloat((rgb >> 8) & 0xFF) / 255,
        blue: CGFloat(rgb & 0xFF) / 255,
        alpha: 1
    )
}

func parseOptions() throws -> Options {
    let arguments = CommandLine.arguments
    guard arguments.count >= 11 else {
        throw HeadlineError.message(usage())
    }
    let input = URL(fileURLWithPath: arguments[1]).standardizedFileURL
    let output = URL(fileURLWithPath: arguments[2]).standardizedFileURL
    var values: [String: String] = [:]
    var index = 3
    while index < arguments.count {
        let key = arguments[index]
        guard key.hasPrefix("--"), index + 1 < arguments.count else {
            throw HeadlineError.message("Invalid option near \(key)\n\(usage())")
        }
        values[key] = arguments[index + 1]
        index += 2
    }
    guard let holdDuration = Double(values["--hold-duration"] ?? "0"),
          let fadeDuration = Double(values["--fade-duration"] ?? values["--duration"] ?? ""),
          holdDuration >= 0,
          fadeDuration > 0 else {
        throw HeadlineError.message("Hold duration must be non-negative and fade duration positive")
    }
    let lines = (1...3).compactMap { values["--line\($0)"] }
    guard lines.count == 3, lines.allSatisfy({ !$0.isEmpty }) else {
        throw HeadlineError.message("--line1, --line2, and --line3 are required")
    }
    guard let baseColorHex = values["--base-color"],
          let accentColorHex = values["--accent-color"] else {
        throw HeadlineError.message("--base-color and --accent-color are required")
    }
    let baseColor = try parseHexColor(baseColorHex, option: "--base-color")
    let accentColor = try parseHexColor(accentColorHex, option: "--accent-color")
    guard input != output else {
        throw HeadlineError.message("Input and output paths must differ")
    }
    return Options(
        input: input,
        output: output,
        holdDuration: holdDuration,
        fadeDuration: fadeDuration,
        lines: lines,
        baseColor: baseColor,
        accentColor: accentColor,
        baseColorHex: baseColorHex,
        accentColorHex: accentColorHex
    )
}

func even(_ value: CGFloat) -> CGFloat {
    let rounded = max(2, Int(value.rounded()))
    return CGFloat(rounded.isMultiple(of: 2) ? rounded : rounded + 1)
}

func frameDuration(for track: AVAssetTrack) async throws -> CMTime {
    let duration = try await track.load(.minFrameDuration)
    guard duration.isValid,
          !duration.isIndefinite,
          duration.value > 0,
          duration.timescale > 0 else {
        throw HeadlineError.message(
            "Source frame duration is unavailable; normalize VFR input with FFmpeg"
        )
    }
    return duration
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
        throw HeadlineError.message("Set FFMPEG_PATH to the verified absolute FFmpeg executable path; PATH fallback is disabled")
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
        throw HeadlineError.message("FFmpeg CFR normalization failed: \(detail)")
    }
}

func makeOverlay(
    size: CGSize,
    lines: [String],
    baseColor: CGColor,
    accentColor: CGColor
) throws -> CGImage {
    let width = Int(size.width)
    let height = Int(size.height)
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    guard let context = CGContext(
        data: nil,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: width * 4,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        throw HeadlineError.message("Cannot create overlay context")
    }
    context.clear(CGRect(origin: .zero, size: size))

    // Keep the title geometry stable when an export preset downsizes the source.
    // The 404 px reference width matches AVAssetExportPresetAppleM4V720pHD's
    // portrait output; every formerly fixed pixel value scales from that canvas.
    let layoutScale = size.width / 404.0
    let boxWidth = size.width * 0.92
    let boxHeight = max(112 * layoutScale, size.height * 0.155)
    let boxRect = CGRect(
        x: (size.width - boxWidth) / 2,
        y: size.height - boxHeight - size.height * 0.035,
        width: boxWidth,
        height: boxHeight
    )
    let availableWidth = boxWidth - 22 * layoutScale
    let baselineStart = boxRect.maxY - 32 * layoutScale
    let spacing = boxHeight * 0.285
    let colors = [baseColor, baseColor, accentColor]

    for (lineIndex, value) in lines.enumerated() {
        var fontSize = min(23 * layoutScale, size.width * 0.057)
        let minimumFontSize = 15 * layoutScale
        var line: CTLine
        while true {
            let font = CTFontCreateWithName("Georgia-BoldItalic" as CFString, fontSize, nil)
            let attributes: [NSAttributedString.Key: Any] = [
                NSAttributedString.Key(kCTFontAttributeName as String): font,
                NSAttributedString.Key(kCTForegroundColorAttributeName as String): colors[lineIndex],
                NSAttributedString.Key(kCTStrokeColorAttributeName as String): CGColor(gray: 0, alpha: 0.95),
                NSAttributedString.Key(kCTStrokeWidthAttributeName as String): -3.0 * layoutScale,
                NSAttributedString.Key(kCTKernAttributeName as String): 0.15 * layoutScale
            ]
            line = CTLineCreateWithAttributedString(
                NSAttributedString(string: value, attributes: attributes)
            )
            let lineWidth = CGFloat(CTLineGetTypographicBounds(line, nil, nil, nil))
            if lineWidth <= availableWidth || fontSize <= minimumFontSize { break }
            fontSize -= 0.5 * layoutScale
        }
        let lineWidth = CGFloat(CTLineGetTypographicBounds(line, nil, nil, nil))
        context.textPosition = CGPoint(
            x: (size.width - lineWidth) / 2,
            y: baselineStart - CGFloat(lineIndex) * spacing
        )
        CTLineDraw(line, context)
    }

    guard let image = context.makeImage() else {
        throw HeadlineError.message("Cannot render overlay image")
    }
    return image
}

@main struct Main {
    static func main() async throws {
        let options = try parseOptions()
        _ = try configuredFFmpeg()
        let asset = AVURLAsset(url: options.input)
        let assetDuration = try await asset.load(.duration)
        guard let sourceVideo = try await asset.loadTracks(withMediaType: .video).first else {
            throw HeadlineError.message("Input has no video track")
        }
        let sourceAudio = try await asset.loadTracks(withMediaType: .audio).first
        let sourceFrameDuration = try await frameDuration(for: sourceVideo)
        let naturalSize = try await sourceVideo.load(.naturalSize)
        let preferredTransform = try await sourceVideo.load(.preferredTransform)
        let transformedRect = CGRect(origin: .zero, size: naturalSize).applying(preferredTransform)
        let renderSize = CGSize(width: even(abs(transformedRect.width)), height: even(abs(transformedRect.height)))
        let normalizedTransform = preferredTransform.concatenating(
            CGAffineTransform(translationX: -transformedRect.minX, y: -transformedRect.minY)
        )
        let compatibleOutput = options.output.pathExtension.lowercased() == "m4v"
        let outputRenderSize: CGSize
        let outputTransform: CGAffineTransform
        if compatibleOutput, renderSize.height > 720 {
            let targetHeight: CGFloat = 720
            let rawWidth = targetHeight * renderSize.width / renderSize.height
            let targetWidth = CGFloat(max(4, Int(floor(rawWidth / 4)) * 4))
            outputRenderSize = CGSize(width: targetWidth, height: targetHeight)
            outputTransform = normalizedTransform.concatenating(CGAffineTransform(
                scaleX: targetWidth / renderSize.width,
                y: targetHeight / renderSize.height
            ))
        } else {
            outputRenderSize = renderSize
            outputTransform = normalizedTransform
        }

        let composition = AVMutableComposition()
        guard let videoTrack = composition.addMutableTrack(
            withMediaType: .video,
            preferredTrackID: kCMPersistentTrackID_Invalid
        ) else {
            throw HeadlineError.message("Cannot create video track")
        }
        try videoTrack.insertTimeRange(
            CMTimeRange(start: .zero, duration: assetDuration),
            of: sourceVideo,
            at: .zero
        )
        if let sourceAudio,
           let audioTrack = composition.addMutableTrack(
            withMediaType: .audio,
            preferredTrackID: kCMPersistentTrackID_Invalid
           ) {
            let audioRange = try await sourceAudio.load(.timeRange)
            let usableDuration = CMTimeMinimum(assetDuration, audioRange.duration)
            try audioTrack.insertTimeRange(
                CMTimeRange(start: audioRange.start, duration: usableDuration),
                of: sourceAudio,
                at: .zero
            )
        }

        let instruction = AVMutableVideoCompositionInstruction()
        instruction.timeRange = CMTimeRange(start: .zero, duration: assetDuration)
        let layerInstruction = AVMutableVideoCompositionLayerInstruction(assetTrack: videoTrack)
        layerInstruction.setTransform(outputTransform, at: .zero)
        instruction.layerInstructions = [layerInstruction]

        let videoComposition = AVMutableVideoComposition()
        videoComposition.instructions = [instruction]
        videoComposition.frameDuration = sourceFrameDuration
        videoComposition.renderSize = outputRenderSize

        let parentLayer = CALayer()
        let videoLayer = CALayer()
        let overlayLayer = CALayer()
        parentLayer.frame = CGRect(origin: .zero, size: outputRenderSize)
        videoLayer.frame = parentLayer.frame
        overlayLayer.frame = parentLayer.frame
        overlayLayer.contents = try makeOverlay(
            size: outputRenderSize,
            lines: options.lines,
            baseColor: options.baseColor,
            accentColor: options.accentColor
        )
        overlayLayer.contentsGravity = .resizeAspectFill
        overlayLayer.opacity = 0

        let totalSeconds = max(
            assetDuration.seconds,
            options.holdDuration + options.fadeDuration + 0.01
        )
        let holdAt = min(0.998, options.holdDuration / totalSeconds)
        let hideAt = min(
            0.999,
            (options.holdDuration + options.fadeDuration) / totalSeconds
        )
        let opacity = CAKeyframeAnimation(keyPath: "opacity")
        opacity.values = [1, 1, 0, 0]
        opacity.keyTimes = [0, NSNumber(value: holdAt), NSNumber(value: hideAt), 1]
        opacity.calculationMode = .linear
        opacity.duration = totalSeconds
        opacity.beginTime = AVCoreAnimationBeginTimeAtZero
        opacity.isRemovedOnCompletion = false
        opacity.fillMode = .forwards
        overlayLayer.add(opacity, forKey: "opening-headline-visibility")

        parentLayer.addSublayer(videoLayer)
        parentLayer.addSublayer(overlayLayer)
        videoComposition.animationTool = AVVideoCompositionCoreAnimationTool(
            postProcessingAsVideoLayer: videoLayer,
            in: parentLayer
        )

        try FileManager.default.createDirectory(
            at: options.output.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let preset = compatibleOutput ? AVAssetExportPresetAppleM4V720pHD : AVAssetExportPresetHighestQuality
        guard let exporter = AVAssetExportSession(asset: composition, presetName: preset) else {
            throw HeadlineError.message("Cannot create exporter")
        }
        let avStagedOutput = stagingURL(for: options.output)
        let finalStagedOutput = stagingURL(for: options.output)
        defer {
            try? FileManager.default.removeItem(at: avStagedOutput)
            try? FileManager.default.removeItem(at: finalStagedOutput)
        }
        exporter.outputURL = avStagedOutput
        exporter.outputFileType = compatibleOutput ? .m4v : .mp4
        exporter.videoComposition = videoComposition
        await exporter.export()
        guard exporter.status == .completed else {
            throw exporter.error ?? HeadlineError.message("Export failed")
        }
        try normalizeCFR(
            input: avStagedOutput,
            output: finalStagedOutput,
            frameDuration: sourceFrameDuration
        )
        try commitStagedOutput(finalStagedOutput, to: options.output)

        print("output=\(options.output.path)")
        print("headline_hold_duration=\(String(format: "%.3f", options.holdDuration))")
        print("headline_fade_duration=\(String(format: "%.3f", options.fadeDuration))")
        print("headline_base_color=\(options.baseColorHex)")
        print("headline_accent_color=\(options.accentColorHex)")
        print("render_size=\(Int(outputRenderSize.width))x\(Int(outputRenderSize.height))")
        print("frame_duration=\(sourceFrameDuration.value)/\(sourceFrameDuration.timescale)")
        print("fps=\(String(format: "%.6f", 1.0 / sourceFrameDuration.seconds))")
    }
}
