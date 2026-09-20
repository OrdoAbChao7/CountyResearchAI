import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";

interface HeaderProps {
  county: string;
  category: string;
  chapterIndex?: number; // 0 to 4
}

const CHAPTERS = ["01 矛盾", "02 历史", "03 数据", "04 困局", "05 启示"];

export const Header: React.FC<HeaderProps> = ({ county, category, chapterIndex = 0 }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const opacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateRight: "clamp",
  });

  // 计算当前已播时间
  const currentSeconds = Math.floor(frame / fps);
  const totalSeconds = Math.floor(durationInFrames / fps);
  const formatTime = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  // 县名雷达微光呼吸
  const radarScale = 1.0 + Math.sin((frame / fps) * 4) * 0.15;

  return (
    <div
      style={{
        position: "absolute",
        top: 60,
        left: 50,
        right: 50,
        display: "flex",
        flexDirection: "column",
        gap: 16,
        opacity,
        zIndex: 50,
        fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
      }}
    >
      {/* 顶部多段章节进度胶囊条 (大幅增强短视频完播引导) */}
      <div
        style={{
          display: "flex",
          gap: 8,
          width: "100%",
        }}
      >
        {CHAPTERS.map((ch, idx) => {
          const isActive = idx === chapterIndex;
          const isPast = idx < chapterIndex;

          return (
            <div
              key={idx}
              style={{
                flex: 1,
                height: 6,
                borderRadius: 3,
                background: isActive
                  ? "linear-gradient(90deg, #3B82F6 0%, #60A5FA 100%)"
                  : isPast
                  ? "rgba(255, 255, 255, 0.7)"
                  : "rgba(255, 255, 255, 0.2)",
                boxShadow: isActive ? "0 0 12px rgba(59, 130, 246, 0.9)" : "none",
                transition: "all 0.3s ease",
              }}
            />
          );
        })}
      </div>

      {/* 顶栏主体信息 */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
          }}
        >
          <div
            style={{
              position: "relative",
              display: "flex",
              alignItems: "center",
            }}
          >
            <div
              style={{
                background: "linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%)",
                color: "#FFFFFF",
                padding: "8px 24px",
                borderRadius: 30,
                fontSize: 26,
                fontWeight: 800,
                letterSpacing: 2,
                boxShadow: "0 4px 20px rgba(37, 99, 235, 0.5)",
                border: "1px solid rgba(255, 255, 255, 0.25)",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  background: "#60A5FA",
                  boxShadow: "0 0 8px #93C5FD",
                  transform: `scale(${radarScale})`,
                }}
              />
              {county}
            </div>
          </div>
          <div
            style={{
              color: "#E2E8F0",
              fontSize: 22,
              fontWeight: 600,
              letterSpacing: 1,
            }}
          >
            {category}
          </div>
        </div>

        {/* 倒计时 / 播放进度指示器 */}
        <div
          style={{
            background: "rgba(15, 23, 42, 0.7)",
            backdropFilter: "blur(16px)",
            border: "1px solid rgba(255, 255, 255, 0.15)",
            padding: "6px 18px",
            borderRadius: 20,
            fontSize: 20,
            fontWeight: 700,
            color: "#93C5FD",
            letterSpacing: 1,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span>⏱</span>
          <span>
            {formatTime(currentSeconds)} / {formatTime(totalSeconds)}
          </span>
        </div>
      </div>
    </div>
  );
};
