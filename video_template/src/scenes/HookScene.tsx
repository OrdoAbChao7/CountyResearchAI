import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { AtmosphereLayer } from "../components/AtmosphereLayer";
import { BackgroundMedia } from "../components/BackgroundMedia";
import { Header } from "../components/Header";
import { SegmentProp } from "../types";

interface HookSceneProps {
  county: string;
  title: string;
  segment: SegmentProp;
}

export const HookScene: React.FC<HookSceneProps> = ({ county, title, segment }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 1. 进场弹性阻尼
  const titleScale = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 140 },
  });

  const cardY = spring({
    frame: Math.max(0, frame - 8),
    fps,
    config: { damping: 15, stiffness: 120 },
  });

  // 2. 视觉留存冲击波动画 (Shockwave Pulse)
  const pulseWave = interpolate(frame % 45, [0, 45], [1, 2.4], {
    extrapolateRight: "clamp",
  });
  const pulseOpacity = interpolate(frame % 45, [0, 45], [0.8, 0], {
    extrapolateRight: "clamp",
  });

  // 3. 高铁动态光束划过 (High-speed Railway Light Streak)
  const streakX = interpolate(frame % 60, [0, 60], [-800, 1400]);

  // 4. 3D 拟态微倾角 (Perspective Gyroscope Tilt)
  const tiltX = Math.sin((frame / fps) * 1.5) * 2.5;
  const tiltY = Math.cos((frame / fps) * 1.2) * 3.0;

  // 5. 标题分词交错动效 (Kinetic Typography Stagger)
  const titleWords = title.split("：");
  const mainTitle = titleWords[0] || title;
  const subTitle = titleWords[1] || "";

  return (
    <div
      style={{
        width: 1080,
        height: 1920,
        position: "relative",
        overflow: "hidden",
        fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
        perspective: 1200,
      }}
    >
      {/* 1. 明亮透气的纪实大图背景 */}
      <BackgroundMedia imageUrl={segment.image_url} />

      {/* 2. 动态高铁光轨速度线 */}
      <svg
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: 1080,
          height: 1920,
          pointerEvents: "none",
          zIndex: 2,
          opacity: 0.35,
        }}
      >
        <line
          x1={streakX}
          y1={650}
          x2={streakX + 500}
          y2={580}
          stroke="url(#railGlow)"
          strokeWidth={4}
          strokeLinecap="round"
        />
        <line
          x1={streakX - 100}
          y1={670}
          x2={streakX + 350}
          y2={600}
          stroke="url(#railGlow)"
          strokeWidth={2}
          strokeLinecap="round"
        />
        <defs>
          <linearGradient id="railGlow" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="rgba(56, 189, 248, 0)" />
            <stop offset="50%" stopColor="rgba(56, 189, 248, 0.9)" />
            <stop offset="100%" stopColor="rgba(255, 255, 255, 1)" />
          </linearGradient>
        </defs>
      </svg>

      {/* 3. 暖琥珀色动态环境微光 */}
      <AtmosphereLayer themeColor="amber" />

      {/* 4. 顶部章节进度条 */}
      <Header county={county} category="核心矛盾 · 01" chapterIndex={0} />

      {/* 5. 主体视觉内容 */}
      <div
        style={{
          position: "absolute",
          top: 350,
          left: 50,
          right: 50,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
          zIndex: 10,
        }}
      >
        {/* 焦点警示胶囊标签 + 冲击波雷达光晕 */}
        <div style={{ position: "relative", marginBottom: 32 }}>
          <div
            style={{
              position: "absolute",
              inset: -8,
              borderRadius: 40,
              border: "2px solid rgba(239, 68, 68, 0.8)",
              transform: `scale(${pulseWave})`,
              opacity: pulseOpacity,
              pointerEvents: "none",
            }}
          />
          <div
            style={{
              background: "linear-gradient(90deg, rgba(239, 68, 68, 0.92) 0%, rgba(220, 38, 38, 0.98) 100%)",
              color: "#FFFFFF",
              padding: "14px 40px",
              borderRadius: 36,
              fontSize: 30,
              fontWeight: 800,
              letterSpacing: 2,
              boxShadow: "0 8px 30px rgba(239, 68, 68, 0.6)",
              border: "1.5px solid rgba(255, 255, 255, 0.4)",
              transform: `scale(${titleScale})`,
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <span>⚡</span>
            <span>{segment.on_screen || "深度反思"}</span>
          </div>
        </div>

        {/* 视频分级大标题 (交错动效) */}
        <h1
          style={{
            fontSize: 72,
            fontWeight: 900,
            color: "#FFFFFF",
            lineHeight: 1.25,
            letterSpacing: 2,
            margin: "0 0 16px 0",
            transform: `scale(${titleScale})`,
            textShadow: "0 8px 32px rgba(0,0,0,0.85)",
          }}
        >
          {mainTitle}
        </h1>

        {subTitle && (
          <div
            style={{
              fontSize: 46,
              fontWeight: 800,
              color: "#FDE047",
              letterSpacing: 2,
              marginBottom: 40,
              textShadow: "0 4px 20px rgba(253, 224, 71, 0.4)",
              transform: `scale(${titleScale})`,
            }}
          >
            {subTitle}
          </div>
        )}

        {/* 矛盾冲突展示 3D 透视毛玻璃卡片 */}
        <div
          style={{
            width: "100%",
            background: "linear-gradient(135deg, rgba(255, 255, 255, 0.16) 0%, rgba(15, 23, 42, 0.76) 100%)",
            backdropFilter: "blur(32px)",
            border: "1.5px solid rgba(255, 255, 255, 0.3)",
            borderRadius: 36,
            padding: "50px 44px",
            boxShadow: "0 30px 70px rgba(0,0,0,0.6), inset 0 1px 2px rgba(255,255,255,0.4)",
            transform: `translateY(${(1 - cardY) * 80}px) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`,
            opacity: cardY,
            transition: "transform 0.1s ease-out",
          }}
        >
          <div
            style={{
              fontSize: 32,
              color: "#93C5FD",
              fontWeight: 800,
              marginBottom: 20,
              letterSpacing: 1.5,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 10,
            }}
          >
            <span>📌</span>
            <span>核心悖论</span>
          </div>

          <p
            style={{
              fontSize: 40,
              color: "#FFFFFF",
              fontWeight: 700,
              lineHeight: 1.6,
              margin: 0,
              textShadow: "0 2px 12px rgba(0,0,0,0.6)",
            }}
          >
            {segment.narration}
          </p>
        </div>
      </div>
    </div>
  );
};
