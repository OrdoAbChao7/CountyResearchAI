import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { AtmosphereLayer } from "../components/AtmosphereLayer";
import { BackgroundMedia } from "../components/BackgroundMedia";
import { Header } from "../components/Header";
import { SegmentProp } from "../types";

interface GrowthSceneProps {
  county: string;
  segment: SegmentProp;
}

export const GrowthScene: React.FC<GrowthSceneProps> = ({ county, segment }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 1. 数字平滑滚动动画
  const counterVal = interpolate(frame, [0, 50], [0, 8], {
    extrapolateRight: "clamp",
  });

  const cardAnim = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 110 },
  });

  // 2. 趋势分化曲线 SVG 绘制动画 (strokeDashoffset)
  const lineDraw = interpolate(frame, [15, 60], [300, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const tiltX = Math.sin((frame / fps) * 1.4) * 2.2;
  const tiltY = Math.cos((frame / fps) * 1.0) * 2.8;

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
      <BackgroundMedia imageUrl={segment.image_url} />
      <AtmosphereLayer themeColor="blue" />
      <Header county={county} category="数据反差 · 03" chapterIndex={2} />

      <div
        style={{
          position: "absolute",
          top: 330,
          left: 50,
          right: 50,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          zIndex: 10,
        }}
      >
        <div
          style={{
            background: "linear-gradient(90deg, #F59E0B 0%, #D97706 100%)",
            color: "#FFFFFF",
            padding: "12px 36px",
            borderRadius: 30,
            fontSize: 28,
            fontWeight: 800,
            letterSpacing: 2,
            marginBottom: 26,
            boxShadow: "0 6px 25px rgba(245, 158, 11, 0.4)",
            border: "1px solid rgba(255, 255, 255, 0.25)",
            transform: `scale(${cardAnim})`,
          }}
        >
          📊 {segment.on_screen || "数据警示"}
        </div>

        {/* 动态大数字毛玻璃看板 + SVG 趋势分化线 */}
        <div
          style={{
            width: "100%",
            background: "linear-gradient(135deg, rgba(255, 255, 255, 0.16) 0%, rgba(15, 23, 42, 0.78) 100%)",
            backdropFilter: "blur(30px)",
            border: "1.5px solid rgba(255, 255, 255, 0.3)",
            borderRadius: 36,
            padding: "38px 40px",
            marginBottom: 28,
            textAlign: "center",
            boxShadow: "0 25px 60px rgba(0,0,0,0.55), inset 0 1px 2px rgba(255,255,255,0.35)",
            transform: `scale(${cardAnim}) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`,
          }}
        >
          <div style={{ fontSize: 28, color: "#93C5FD", fontWeight: 700, marginBottom: 10 }}>
            户籍人口 vs 常住人口 外流差额
          </div>
          
          <div
            style={{
              fontSize: 112,
              fontWeight: 900,
              background: "linear-gradient(180deg, #FF4565 0%, #FF8A9E 100%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              letterSpacing: -2,
              lineHeight: 1.1,
              filter: "drop-shadow(0 8px 24px rgba(244,63,94,0.5))",
            }}
          >
            {counterVal < 5 ? `${counterVal.toFixed(0)}` : "5 - 8"}{" "}
            <span style={{ fontSize: 50, fontWeight: 800, color: "#FDA4AF" }}>万人</span>
          </div>

          {/* 动态趋势折线图 (SVG) */}
          <div style={{ margin: "16px 0 10px 0", height: 64, position: "relative" }}>
            <svg width="100%" height="64" viewBox="0 0 400 64" style={{ overflow: "visible" }}>
              {/* 基准线 */}
              <line x1="10" y1="50" x2="390" y2="50" stroke="rgba(255,255,255,0.15)" strokeDasharray="4 4" />
              {/* 外流加速曲线 */}
              <path
                d="M 10 45 Q 150 42, 260 25 T 390 8"
                fill="none"
                stroke="#F43F5E"
                strokeWidth="4"
                strokeDasharray="300"
                strokeDashoffset={lineDraw}
                strokeLinecap="round"
              />
              <circle cx="390" cy="8" r="5" fill="#FDA4AF" />
            </svg>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 18,
                color: "#94A3B8",
                marginTop: 2,
              }}
            >
              <span>高铁通车前 (平稳)</span>
              <span style={{ color: "#F43F5E", fontWeight: 700 }}>通车后 (加速外流) ↗</span>
            </div>
          </div>

          {/* 进度光条 */}
          <div
            style={{
              height: 8,
              borderRadius: 4,
              background: "rgba(255, 255, 255, 0.15)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${Math.min(100, (counterVal / 8) * 100)}%`,
                height: "100%",
                background: "linear-gradient(90deg, #F43F5E 0%, #FB7185 100%)",
                borderRadius: 4,
                boxShadow: "0 0 12px rgba(244, 63, 94, 0.8)",
              }}
            />
          </div>
        </div>

        {/* 悬浮网友热评贴纸 (弹幕共鸣感) */}
        <div
          style={{
            width: "100%",
            background: "rgba(30, 41, 59, 0.7)",
            backdropFilter: "blur(20px)",
            borderRadius: 20,
            border: "1px solid rgba(244, 63, 94, 0.35)",
            padding: "12px 24px",
            marginBottom: 24,
            display: "flex",
            alignItems: "center",
            gap: 14,
            boxShadow: "0 10px 25px rgba(0,0,0,0.3)",
          }}
        >
          <span style={{ fontSize: 24 }}>💬</span>
          <span style={{ fontSize: 22, color: "#E2E8F0", fontWeight: 600 }}>
            “去大湾区只要一个多小时，周末回，周一走，成了睡城...”
          </span>
        </div>

        {/* 叙述详情卡片 */}
        <div
          style={{
            width: "100%",
            background: "linear-gradient(135deg, rgba(255, 255, 255, 0.12) 0%, rgba(15, 23, 42, 0.72) 100%)",
            backdropFilter: "blur(28px)",
            border: "1.5px solid rgba(255, 255, 255, 0.25)",
            borderRadius: 32,
            padding: "40px 38px",
            boxShadow: "0 20px 50px rgba(0,0,0,0.5)",
          }}
        >
          <p
            style={{
              fontSize: 38,
              color: "#FFFFFF",
              lineHeight: 1.65,
              fontWeight: 600,
              margin: 0,
              textShadow: "0 2px 10px rgba(0,0,0,0.6)",
            }}
          >
            {segment.narration}
          </p>
        </div>
      </div>
    </div>
  );
};
