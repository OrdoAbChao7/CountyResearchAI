import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { AtmosphereLayer } from "../components/AtmosphereLayer";
import { BackgroundMedia } from "../components/BackgroundMedia";
import { Header } from "../components/Header";
import { SegmentProp } from "../types";

interface TakeawaySceneProps {
  county: string;
  segment: SegmentProp;
}

export const TakeawayScene: React.FC<TakeawaySceneProps> = ({ county, segment }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scale = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 110 },
  });

  // 点赞 +1 浮动光晕动效
  const likeFloatY = interpolate(frame % 45, [0, 45], [0, -16], {
    extrapolateRight: "clamp",
  });
  const likeOpacity = interpolate(frame % 45, [0, 45], [1, 0], {
    extrapolateRight: "clamp",
  });

  const tiltX = Math.sin((frame / fps) * 1.2) * 2.0;
  const tiltY = Math.cos((frame / fps) * 1.0) * 2.5;

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
      <AtmosphereLayer themeColor="gold" />
      <Header county={county} category="总结启示 · 05" chapterIndex={4} />

      <div
        style={{
          position: "absolute",
          top: 340,
          left: 50,
          right: 50,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
          zIndex: 10,
        }}
      >
        <div
          style={{
            background: "linear-gradient(90deg, #F59E0B 0%, #D97706 100%)",
            color: "#FFFFFF",
            padding: "12px 38px",
            borderRadius: 30,
            fontSize: 28,
            fontWeight: 800,
            letterSpacing: 2,
            marginBottom: 28,
            boxShadow: "0 6px 25px rgba(245, 158, 11, 0.4)",
            border: "1px solid rgba(255, 255, 255, 0.25)",
            transform: `scale(${scale})`,
          }}
        >
          💡 {segment.on_screen || "终局思考"}
        </div>

        {/* 核心金句大毛玻璃卡片 */}
        <div
          style={{
            width: "100%",
            background: "linear-gradient(135deg, rgba(255, 255, 255, 0.16) 0%, rgba(20, 16, 10, 0.78) 100%)",
            backdropFilter: "blur(32px)",
            border: "2px solid rgba(245, 158, 11, 0.5)",
            borderRadius: 38,
            padding: "48px 44px",
            boxShadow:
              "0 25px 60px rgba(0,0,0,0.65), 0 0 40px rgba(245,158,11,0.2), inset 0 1px 2px rgba(255,255,255,0.35)",
            transform: `scale(${scale}) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`,
          }}
        >
          <div
            style={{
              fontSize: 62,
              fontWeight: 900,
              background: "linear-gradient(180deg, #FFFBEB 0%, #FDE68A 50%, #F59E0B 100%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              lineHeight: 1.35,
              marginBottom: 26,
              letterSpacing: 2,
              filter: "drop-shadow(0 6px 20px rgba(245,158,11,0.4))",
            }}
          >
            “交通是通道，
            <br />
            不是终点。”
          </div>

          <div
            style={{
              height: 2,
              background: "linear-gradient(90deg, transparent, rgba(245,158,11,0.6), transparent)",
              marginBottom: 26,
            }}
          />

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

          {/* 权威信源背书 */}
          <div
            style={{
              marginTop: 28,
              paddingTop: 18,
              borderTop: "1px solid rgba(255, 255, 255, 0.12)",
              fontSize: 20,
              color: "#CBD5E1",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
            }}
          >
            <span>📊</span>
            <span>信源依据：信丰县国民经济发展统计公报 / 七普人口普查</span>
          </div>

          {/* 互动转化与关注条 (带微光动效) */}
          <div
            style={{
              marginTop: 28,
              padding: "16px 28px",
              borderRadius: 24,
              background: "linear-gradient(90deg, rgba(245, 158, 11, 0.25) 0%, rgba(217, 119, 6, 0.35) 100%)",
              border: "1.5px solid rgba(245, 158, 11, 0.5)",
              fontSize: 26,
              color: "#FDE68A",
              fontWeight: 800,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 14,
              position: "relative",
              boxShadow: "0 8px 25px rgba(245, 158, 11, 0.3)",
            }}
          >
            <span>👍 点赞关注</span>
            <span>·</span>
            <span>洞察中国县域经济变局</span>

            {/* +1 粒子浮动效果 */}
            <div
              style={{
                position: "absolute",
                top: -10,
                right: 30,
                color: "#FDE047",
                fontSize: 20,
                fontWeight: 900,
                transform: `translateY(${likeFloatY}px)`,
                opacity: likeOpacity,
                pointerEvents: "none",
              }}
            >
              +1
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
