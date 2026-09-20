import React from "react";
import { Audio, interpolate, Sequence, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Captions } from "./components/Captions";
import { DeclineScene } from "./scenes/DeclineScene";
import { GrowthScene } from "./scenes/GrowthScene";
import { HookScene } from "./scenes/HookScene";
import { OriginScene } from "./scenes/OriginScene";
import { TakeawayScene } from "./scenes/TakeawayScene";
import { VideoProps } from "./types";

const SceneTransitionWrapper: React.FC<{
  children: React.ReactNode;
  durationInFrames: number;
}> = ({ children, durationInFrames }) => {
  const frame = useCurrentFrame();
  const fadeIn = interpolate(frame, [0, 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [durationInFrames - 8, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = Math.min(fadeIn, fadeOut);
  const scale = interpolate(frame, [0, 8], [0.97, 1.0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        opacity,
        transform: `scale(${scale})`,
      }}
    >
      {children}
    </div>
  );
};

export const CountyVideo: React.FC<VideoProps> = ({
  county,
  title,
  audio_url,
  bgm_url,
  sfx_url,
  segments,
  subtitles,
}) => {
  const { fps, durationInFrames: totalDurationFrames } = useVideoConfig();

  const resolveAudioSrc = (src: string) => {
    if (!src) return "";
    if (src.startsWith("http://") || src.startsWith("https://") || src.startsWith("data:")) {
      return src;
    }
    return staticFile(src);
  };

  // 为每个段位计算起始帧与帧长度
  let accumulatedFrames = 0;
  const sequenceConfigs = segments.map((seg, idx) => {
    const from = accumulatedFrames;
    const durationInFrames = Math.max(
      Math.round((seg.duration_ms / 1000) * fps),
      fps * 2 // 至少保证 2 秒展示
    );
    accumulatedFrames += durationInFrames;
    return {
      segment: seg,
      from,
      durationInFrames,
      index: idx,
    };
  });

  return (
    <div style={{ flex: 1, backgroundColor: "#000000" }}>
      {/* 旁白音频轨 (居中最高优先级) */}
      {audio_url && <Audio src={resolveAudioSrc(audio_url)} volume={1.0} />}

      {/* 沉浸式环境 BGM 音频轨 (智能压音 Audio Ducking) */}
      {bgm_url && (
        <Audio
          src={resolveAudioSrc(bgm_url)}
          loop
          volume={(f) =>
            interpolate(
              f,
              [0, 30, totalDurationFrames - 60, totalDurationFrames],
              [0.24, 0.08, 0.08, 0.28],
              {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              }
            )
          }
        />
      )}

      {/* 开篇重音音效 */}
      {sfx_url && (
        <Sequence from={0} durationInFrames={Math.round(fps * 1.5)}>
          <Audio src={resolveAudioSrc(sfx_url)} volume={0.65} />
        </Sequence>
      )}

      {/* 分段动态场景 */}
      {sequenceConfigs.map((cfg) => {
        const segId = cfg.segment.segment_id;

        return (
          <Sequence
            key={segId + cfg.index}
            from={cfg.from}
            durationInFrames={cfg.durationInFrames}
          >
            <SceneTransitionWrapper durationInFrames={cfg.durationInFrames}>
              {segId === "hook" && (
                <HookScene
                  county={county}
                  title={title}
                  segment={cfg.segment}
                />
              )}
              {segId === "origin" && (
                <OriginScene
                  county={county}
                  segment={cfg.segment}
                />
              )}
              {segId === "growth" && (
                <GrowthScene
                  county={county}
                  segment={cfg.segment}
                />
              )}
              {segId === "decline" && (
                <DeclineScene
                  county={county}
                  segment={cfg.segment}
                />
              )}
              {segId === "takeaway" && (
                <TakeawayScene
                  county={county}
                  segment={cfg.segment}
                />
              )}
            </SceneTransitionWrapper>
          </Sequence>
        );
      })}

      {/* 全局时间轴同步字幕 */}
      {subtitles && subtitles.length > 0 && <Captions subtitles={subtitles} />}
    </div>
  );
};

