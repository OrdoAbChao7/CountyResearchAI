import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { SubtitleItem } from "../types";

interface CaptionsProps {
  subtitles: SubtitleItem[];
}

// 重点高亮关键词模式匹配
const HIGHLIGHT_REGEX = /(高铁|高速|信丰|广东|赣深|赣粤驿道|5到8万人|5-8万|37%|过路经济|落地经济|通道|终点|空心化|单极集中)/g;

export const Captions: React.FC<CaptionsProps> = ({ subtitles }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentMs = (frame / fps) * 1000;

  // 寻找当前毫秒对应的字幕条目
  const currentSub = subtitles.find(
    (s) => currentMs >= s.start_ms - 50 && currentMs <= s.end_ms + 100
  );

  if (!currentSub) {
    return null;
  }

  // 针对当前字幕条目出现的微小弹跳动画
  const subStartFrame = Math.floor((currentSub.start_ms / 1000) * fps);
  const relativeFrame = Math.max(0, frame - subStartFrame);

  const scale = spring({
    frame: relativeFrame,
    fps,
    config: { damping: 14, stiffness: 180 },
  });

  // 计算当前句子播放的进度百分比 (0.0 -> 1.0)
  const durationMs = Math.max(1, currentSub.end_ms - currentSub.start_ms);
  const progressRatio = Math.min(1, Math.max(0, (currentMs - currentSub.start_ms) / durationMs));

  // 渲染带有重点词高亮 + 实时朗读呼吸感
  const renderHighlightedText = (text: string) => {
    const parts = text.split(HIGHLIGHT_REGEX);
    let charOffset = 0;
    const totalChars = text.length;

    return parts.map((part, i) => {
      const isKeyword = HIGHLIGHT_REGEX.test(part);
      const partStartRatio = charOffset / totalChars;
      const partEndRatio = (charOffset + part.length) / totalChars;
      charOffset += part.length;

      // 判断该词是否正在被念读
      const isCurrentlySpoken = progressRatio >= partStartRatio && progressRatio <= partEndRatio;

      if (isKeyword) {
        return (
          <span
            key={i}
            style={{
              color: "#FDE047", // 醒目亮黄色高亮
              fontWeight: 900,
              textShadow: isCurrentlySpoken
                ? "0 0 24px rgba(253, 224, 71, 0.9)"
                : "0 0 16px rgba(253, 224, 71, 0.5)",
              padding: "0 4px",
              transform: isCurrentlySpoken ? "scale(1.05)" : "scale(1)",
              display: "inline-block",
              transition: "transform 0.1s ease",
            }}
          >
            {part}
          </span>
        );
      }

      return (
        <span
          key={i}
          style={{
            color: isCurrentlySpoken ? "#FFFFFF" : "#E2E8F0",
            fontWeight: isCurrentlySpoken ? 800 : 700,
          }}
        >
          {part}
        </span>
      );
    });
  };

  return (
    <div
      style={{
        position: "absolute",
        bottom: 120,
        left: 40,
        right: 40,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        zIndex: 100,
        pointerEvents: "none",
        fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
      }}
    >
      <div
        style={{
          transform: `scale(${scale})`,
          background: "rgba(15, 23, 42, 0.82)",
          backdropFilter: "blur(26px)",
          border: "1.5px solid rgba(255, 255, 255, 0.28)",
          boxShadow:
            "0 15px 45px rgba(0, 0, 0, 0.65), inset 0 1px 1px rgba(255, 255, 255, 0.35)",
          padding: "18px 42px",
          borderRadius: 30,
          maxWidth: 1000,
          textAlign: "center",
        }}
      >
        <span
          style={{
            fontSize: 42,
            fontWeight: 800,
            letterSpacing: 1.5,
            lineHeight: 1.45,
            textShadow: "0 2px 12px rgba(0,0,0,0.8)",
          }}
        >
          {renderHighlightedText(currentSub.text)}
        </span>
      </div>
    </div>
  );
};
