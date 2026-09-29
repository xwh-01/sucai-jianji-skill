import AVFoundation
import CoreGraphics
import CoreVideo
import Foundation

enum PunchEndError: Error, CustomStringConvertible {
    case message(String)

    var description: String {
        switch self { case .message(let value): return value }
    }
}

struct Options {
    let input: URL
    let output: URL
    let audioMode: String
    let soundVideo: URL?
    let soundStart: Double?
    let cutTime: Double?
    let effectDuration: Double
    let motion: String
    let zoomScale: Double
    let zoomDelay: Double
    let zoomDuration: Double
    let shakeDuration: Double
    let shakeAmplitude: Double
}

func usage() -> String {
    """
    usage: apply_punch_end <input.mp4> <output.mp4> \\
      [--audio-mode <silence|impact>] \\
      [--sound-video <reference.mp4> --sound-start <seconds>] \\
      [--cut-time <seconds>] [--effect-duration <seconds>] \\
      [--motion <zoom|shake|punch|hold>] \\
      [--zoom-scale <ratio>] [--zoom-delay <seconds>] \\
      [--zoom-duration <seconds>] [--shake-duration <seconds>] \\
      [--shake-amplitude <pixels>]

    defaults:
      cut-time=input duration, effect-duration=1.0, audio-mode=impact when sound-video is set otherwise silence, motion=shake,
      zoom-scale=1.14, zoom-delay=0.20, zoom-duration=0.30,
      shake-duration=0.45, shake-amplitude=10
    """
}

func parseOptions() throws -> Options {
    let args = CommandLine.arguments
    guard args.count >= 3 else { throw PunchEndError.message(usage()) }
    let input = URL(fileURLWithPath: args[1])
    let output = URL(fileURLWithPath: args[2])
    var values: [String: String] = [:]
    var index = 3
    while index < args.count {
        let key = args[index]
        guard key.hasPrefix("--"), index + 1 < args.count else {
            throw PunchEndError.message("Invalid argument: \(key)\n\(usage())")
        }
        values[key] = args[index + 1]
        index += 2
    }
    let audioMode = values["--audio-mode"] ?? (values["--sound-video"] == nil ? "silence" : "impact")
    guard ["silence", "impact"].contains(audioMode) else {
        throw PunchEndError.message("--audio-mode must be silence or impact")
    }
    var soundVideo: URL?
    var soundStart: Double?
    if audioMode == "impact" {
        guard let soundPath = values["--sound-video"],
              let soundStartText = values["--sound-start"],
              let parsedSoundStart = Double(soundStartText), parsedSoundStart >= 0 else {
            throw PunchEndError.message("impact mode requires --sound-video and --sound-start\n\(usage())")
        }
        soundVideo = URL(fileURLWithPath: soundPath)
        soundStart = parsedSoundStart
    }
    let cutTime = try values["--cut-time"].map {
        guard let value = Double($0), value > 0 else { throw PunchEndError.message("Invalid --cut-time") }
        return value
    }
    let effectDuration = Double(values["--effect-duration"] ?? "1.0") ?? -1
    let motion = values["--motion"] ?? "shake"
    let zoomScale = Double(values["--zoom-scale"] ?? "1.14") ?? -1
    let zoomDelay = Double(values["--zoom-delay"] ?? "0.20") ?? -1
    let zoomDuration = Double(values["--zoom-duration"] ?? "0.30") ?? -1
    let shakeDuration = Double(values["--shake-duration"] ?? "0.45") ?? -1
    let shakeAmplitude = Double(values["--shake-amplitude"] ?? "10") ?? -1
    guard effectDuration > 0, zoomScale >= 1, zoomDelay >= 0,
          zoomDuration > 0,
          ["zoom", "shake", "punch", "hold"].contains(motion), shakeDuration > 0,
          shakeAmplitude >= 0 else {
        throw PunchEndError.message("Invalid effect timing or zoom values")
    }
    if motion == "zoom" && zoomDelay + zoomDuration > effectDuration {
        throw PunchEndError.message("Zoom timing exceeds effect duration")
    }
    if motion == "shake" && zoomDelay + shakeDuration > effectDuration {
        throw PunchEndError.message("Shake timing exceeds effect duration")
    }
    if motion == "punch" && zoomDelay > effectDuration {
        throw PunchEndError.message("Punch timing exceeds effect duration")
    }
    return Options(
        input: input,
        output: output,
        audioMode: audioMode,
        soundVideo: soundVideo,
        soundStart: soundStart,
        cutTime: cutTime,
        effectDuration: effectDuration,
        motion: motion,
        zoomScale: zoomScale,
        zoomDelay: zoomDelay,
        zoomDuration: zoomDuration,
        shakeDuration: shakeDuration,
        shakeAmplitude: shakeAmplitude
    )
}

func makeEndVideo(
    frame: CGImage,
    duration: Double,
    motion: String,
    zoomScale: Double,
    zoomDelay: Double,
    zoomDuration: Double,
    shakeDuration: Double,
    shakeAmplitude: Double,
    frameDuration: CMTime,
    output: URL
) async throws {
    let width = frame.width
    let height = frame.height
    let frameSeconds = frameDuration.seconds
    let frameCount = Int(ceil(duration / frameSeconds))
    try? FileManager.default.removeItem(at: output)
    let writer = try AVAssetWriter(outputURL: output, fileType: .mov)
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
    guard writer.canAdd(input) else { throw PunchEndError.message("Cannot add zoom video input") }
    writer.add(input)
    guard writer.startWriting() else {
        throw writer.error ?? PunchEndError.message("Cannot start zoom writer")
    }
    writer.startSession(atSourceTime: .zero)

    for index in 0..<frameCount {
        while !input.isReadyForMoreMediaData { try await Task.sleep(for: .milliseconds(2)) }
        var optionalBuffer: CVPixelBuffer?
        CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_32BGRA,
            attributes as CFDictionary,
            &optionalBuffer
        )
        guard let buffer = optionalBuffer else { throw PunchEndError.message("Cannot allocate zoom frame") }
        CVPixelBufferLockBaseAddress(buffer, [])
        guard let context = CGContext(
            data: CVPixelBufferGetBaseAddress(buffer),
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
        ) else { throw PunchEndError.message("Cannot create zoom frame context") }

        let seconds = Double(index) * frameSeconds
        let baseRect = CGRect(x: 0, y: 0, width: width, height: height)
        if motion == "hold" {
            context.draw(frame, in: baseRect)
        } else if motion == "shake" {
            context.draw(frame, in: baseRect)
            if seconds >= zoomDelay && seconds <= zoomDelay + shakeDuration {
                let elapsed = seconds - zoomDelay
                let progress = min(max(elapsed / shakeDuration, 0), 1)
                // A short, asymmetric impact and recoil reads more naturally than
                // a regular high-frequency sine wave.
                let keyframes: [(time: Double, x: Double, y: Double)] = [
                    (0.00,  0.00,  0.00),
                    (0.08, -0.85,  0.32),
                    (0.18,  0.70, -0.42),
                    (0.32, -0.50,  0.30),
                    (0.48,  0.32, -0.22),
                    (0.66, -0.17,  0.12),
                    (0.84,  0.06, -0.04),
                    (1.00,  0.00,  0.00)
                ]
                let upperIndex = keyframes.firstIndex { $0.time >= progress } ?? keyframes.count - 1
                let lowerIndex = max(upperIndex - 1, 0)
                let lower = keyframes[lowerIndex]
                let upper = keyframes[upperIndex]
                let span = max(upper.time - lower.time, 0.0001)
                let segmentProgress = min(max((progress - lower.time) / span, 0), 1)
                let eased = segmentProgress * segmentProgress * (3 - 2 * segmentProgress)
                let x = shakeAmplitude * (lower.x + (upper.x - lower.x) * eased)
                let y = shakeAmplitude * (lower.y + (upper.y - lower.y) * eased)
                context.draw(frame, in: baseRect.offsetBy(dx: x, dy: y))
            }
        } else if motion == "punch" {
            // Match the source episodes: hold the final frame, jump to a tighter
            // crop on the sound hit, then keep that enlarged frame perfectly still.
            let scale = seconds < zoomDelay ? 1 : zoomScale
            let drawWidth = Double(width) * scale
            let drawHeight = Double(height) * scale
            context.draw(frame, in: CGRect(
                x: (Double(width) - drawWidth) / 2,
                y: (Double(height) - drawHeight) / 2,
                width: drawWidth,
                height: drawHeight
            ))
        } else {
            let linear = min(max((seconds - zoomDelay) / zoomDuration, 0), 1)
            let eased = 1 - pow(1 - linear, 3)
            let scale = 1 + (zoomScale - 1) * eased
            let drawWidth = Double(width) * scale
            let drawHeight = Double(height) * scale
            context.draw(frame, in: CGRect(
                x: (Double(width) - drawWidth) / 2,
                y: (Double(height) - drawHeight) / 2,
                width: drawWidth,
                height: drawHeight
            ))
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])
        guard adaptor.append(
            buffer,
            withPresentationTime: CMTimeMultiply(frameDuration, multiplier: Int32(index))
        ) else {
            throw writer.error ?? PunchEndError.message("Cannot append zoom frame")
        }
    }
    input.markAsFinished()
    await writer.finishWriting()
    guard writer.status == .completed else {
        throw writer.error ?? PunchEndError.message("Zoom video write failed")
    }
}

func frameDuration(for track: AVAssetTrack) async throws -> CMTime {
    let duration = try await track.load(.minFrameDuration)
    guard duration.isValid,
          !duration.isIndefinite,
          duration.value > 0,
          duration.timescale > 0 else {
        throw PunchEndError.message(
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
        throw PunchEndError.message("Set FFMPEG_PATH to the verified absolute FFmpeg executable path; PATH fallback is disabled")
    }
    return URL(fileURLWithPath: path)
}

func normalizeCFR(
    input: URL,
    output: URL,
    frameDuration: CMTime,
    cutTime: Double,
    effectDuration: Double,
    audioMode: String,
    soundVideo: URL?,
    soundStart: Double?
) throws {
    let process = Process()
    let errorPipe = Pipe()
    process.executableURL = try configuredFFmpeg()
    let totalDuration = cutTime + effectDuration
    var arguments = [
        "-hide_banner", "-loglevel", "error", "-y",
        "-i", input.path
    ]
    if audioMode == "impact" {
        guard let soundVideo, let soundStart else {
            throw PunchEndError.message("Missing impact sound options during FFmpeg mux")
        }
        arguments += [
            "-ss", String(format: "%.6f", soundStart),
            "-t", String(format: "%.6f", effectDuration),
            "-i", soundVideo.path,
            "-filter_complex",
            "[0:a:0]atrim=end=\(cutTime),apad=whole_dur=\(cutTime),atrim=end=\(cutTime),asetpts=PTS-STARTPTS[a0];" +
            "[1:a:0]atrim=end=\(effectDuration),asetpts=PTS-STARTPTS[a1];" +
            "[a0][a1]concat=n=2:v=0:a=1[aout]",
            "-map", "0:v:0", "-map", "[aout]"
        ]
    } else {
        arguments += [
            "-filter_complex",
            "[0:a:0]apad=whole_dur=\(totalDuration),atrim=end=\(totalDuration),asetpts=PTS-STARTPTS[aout]",
            "-map", "0:v:0", "-map", "[aout]"
        ]
    }
    arguments += [
        "-t", String(format: "%.6f", totalDuration),
        "-fps_mode", "cfr", "-r", "\(frameDuration.timescale)/\(frameDuration.value)",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", output.path
    ]
    process.arguments = arguments
    process.standardError = errorPipe
    try process.run()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else {
        let data = errorPipe.fileHandleForReading.readDataToEndOfFile()
        let detail = String(data: data, encoding: .utf8) ?? "unknown FFmpeg error"
        throw PunchEndError.message("FFmpeg CFR normalization failed: \(detail)")
    }
}

@main struct Main {
    static func main() async throws {
        let options = try parseOptions()
        _ = try configuredFFmpeg()
        let inputAsset = AVURLAsset(url: options.input)
        let inputDuration = CMTimeGetSeconds(try await inputAsset.load(.duration))
        let cutTime = options.cutTime ?? inputDuration
        guard cutTime > 0.1, cutTime <= inputDuration + 0.01 else {
            throw PunchEndError.message("cut-time is outside the input duration")
        }
        if options.audioMode == "impact" {
            guard let soundVideo = options.soundVideo, let soundStart = options.soundStart else {
                throw PunchEndError.message("Missing impact sound options")
            }
            let soundAsset = AVURLAsset(url: soundVideo)
            guard soundStart + options.effectDuration <= CMTimeGetSeconds(try await soundAsset.load(.duration)) + 0.01 else {
                throw PunchEndError.message("sound interval exceeds the reference duration")
            }
            guard try await soundAsset.loadTracks(withMediaType: .audio).first != nil else {
                throw PunchEndError.message("Impact reference has no audio track")
            }
        }

        guard let sourceVideo = try await inputAsset.loadTracks(withMediaType: .video).first else {
            throw PunchEndError.message("Input has no video track")
        }
        let sourceFrameDuration = try await frameDuration(for: sourceVideo)
        let frameSeconds = sourceFrameDuration.seconds
        let generator = AVAssetImageGenerator(asset: inputAsset)
        generator.appliesPreferredTrackTransform = true
        generator.requestedTimeToleranceBefore = .zero
        generator.requestedTimeToleranceAfter = .zero
        var actual = CMTime.zero
        let frameTime = max(0, cutTime - frameSeconds)
        let finalFrame = try generator.copyCGImage(
            at: CMTime(seconds: frameTime, preferredTimescale: 600),
            actualTime: &actual
        )

        try FileManager.default.createDirectory(
            at: options.output.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let workDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("punch-end-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: workDirectory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: workDirectory) }
        let workVideo = workDirectory.appendingPathComponent("hold.mov")
        try await makeEndVideo(
            frame: finalFrame,
            duration: options.effectDuration,
            motion: options.motion,
            zoomScale: options.zoomScale,
            zoomDelay: options.zoomDelay,
            zoomDuration: options.zoomDuration,
            shakeDuration: options.shakeDuration,
            shakeAmplitude: options.shakeAmplitude,
            frameDuration: sourceFrameDuration,
            output: workVideo
        )

        let zoomAsset = AVURLAsset(url: workVideo)
        guard let zoomVideo = try await zoomAsset.loadTracks(withMediaType: .video).first else {
            throw PunchEndError.message("Missing required hold video track")
        }
        let sourceAudio = try await inputAsset.loadTracks(withMediaType: .audio).first
        let composition = AVMutableComposition()
        guard let outVideo = composition.addMutableTrack(
            withMediaType: .video,
            preferredTrackID: kCMPersistentTrackID_Invalid
        ), let outAudio = composition.addMutableTrack(
            withMediaType: .audio,
            preferredTrackID: kCMPersistentTrackID_Invalid
        ) else { throw PunchEndError.message("Cannot create output tracks") }

        let cut = CMTime(seconds: cutTime, preferredTimescale: 600)
        let storyRange = CMTimeRange(start: .zero, duration: cut)
        try outVideo.insertTimeRange(storyRange, of: sourceVideo, at: .zero)
        if let sourceAudio {
            try outAudio.insertTimeRange(storyRange, of: sourceAudio, at: .zero)
        } else {
            outAudio.insertEmptyTimeRange(storyRange)
        }
        let effectTime = CMTime(seconds: options.effectDuration, preferredTimescale: 600)
        try outVideo.insertTimeRange(
            CMTimeRange(start: .zero, duration: effectTime),
            of: zoomVideo,
            at: cut
        )
        outAudio.insertEmptyTimeRange(CMTimeRange(start: cut, duration: effectTime))

        let compatibleOutput = options.output.pathExtension.lowercased() == "m4v"
        let preset = compatibleOutput
            ? AVAssetExportPresetAppleM4V720pHD
            : AVAssetExportPresetHighestQuality
        guard let exporter = AVAssetExportSession(asset: composition, presetName: preset) else {
            throw PunchEndError.message("Cannot create final exporter")
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
        exporter.videoComposition = videoComposition
        await exporter.export()
        guard exporter.status == .completed else {
            throw exporter.error ?? PunchEndError.message("Final export failed")
        }
        try normalizeCFR(
            input: avStagedOutput,
            output: finalStagedOutput,
            frameDuration: sourceFrameDuration,
            cutTime: cutTime,
            effectDuration: options.effectDuration,
            audioMode: options.audioMode,
            soundVideo: options.soundVideo,
            soundStart: options.soundStart
        )
        try commitStagedOutput(finalStagedOutput, to: options.output)
        print("output=\(options.output.path)")
        print(String(format: "cut_time=%.3f", cutTime))
        print(String(format: "frame_time=%.3f", CMTimeGetSeconds(actual)))
        print(String(format: "effect_duration=%.3f", options.effectDuration))
        print("frame_duration=\(sourceFrameDuration.value)/\(sourceFrameDuration.timescale)")
        print("fps=\(String(format: "%.6f", 1.0 / frameSeconds))")
        print("motion=\(options.motion)")
        print("audio_mode=\(options.audioMode)")
        print(String(format: "output_duration=%.3f", cutTime + options.effectDuration))
    }
}
