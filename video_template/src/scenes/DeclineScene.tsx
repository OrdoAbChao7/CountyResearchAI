import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { AtmosphereLayer } from "../components/AtmosphereLayer";
import { BackgroundMedia } from "../components/BackgroundMedia";
import { Header } from "../components/Header";
import { SegmentProp } from "../types";

interface DeclineSceneProps {
  county: string;
  segment: SegmentProp;
}

export const DeclineScene: React.FC<DeclineSceneProps> = ({ county, segment }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 120 },
  });

  // 虹吸流动箭头动画 (Siphon flow animation)
  const arrowOffset = interpolate(frame % 30, [0, 30], [0, 24]);
  const tiltX = Math.sin((frame / fps) * 1.5) * 2.0;
  const tiltY = Math.cos((frame / fps) * 1.2) * 2.5;

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
      <AtmosphereLayer themeColor="rose" />
      <Header county={county} category="结构失衡 · 04" chapterIndex={3} />

      <div
        style={{
          position: "absolute",
          top: 340,
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
            background: "linear-gradient(90deg, #E11D48 0%, #BE123C 100%)",
            color: "#FFFFFF",
            padding: "12px 36px",
            borderRadius: 30,
            fontSize: 28,
            fontWeight: 800,
            letterSpacing: 2,
            marginBottom: 28,
            boxShadow: "0 6px 25px rgba(225, 29, 72, 0.4)",
            border: "1px solid rgba(255, 255, 255, 0.25)",
            transform: `scale(${progress})`,
          }}
        >
          ⚠️ {segment.on_screen || "空心化危机"}
        </div>

        {/* 左右分屏对比毛玻璃卡片 + 虹吸流动效果 */}
        <div
          style={{
            width: "100%",
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 20,
            marginBottom: 24,
            transform: `scale(${progress}) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`,
            position: "relative",
          }}
        >
          {/* 左侧: 县城单极集中 */}
          <div
            style={{
              background: "linear-gradient(135deg, rgba(244, 63, 94, 0.3) 0%, rgba(15, 23, 42, 0.85) 100%)",
              backdropFilter: "blur(26px)",
              border: "1.5px solid rgba(244, 63, 94, 0.5)",
              borderRadius: 30,
              padding: "36px 20px",
              textAlign: "center",
              boxShadow: "0 15px 35px rgba(244, 63, 94, 0.3)",
            }}
          >
            <div style={{ fontSize: 24, color: "#FDA4AF", fontWeight: 700, marginBottom: 8 }}>
              核心城区 (嘉定镇)
            </div>
            <div style={{ fontSize: 68, fontWeight: 900, color: "#FFFFFF" }}>
              37%+
            </div>
            <div style={{ fontSize: 22, color: "#FDA4AF", marginTop: 8, fontWeight: 600 }}>
              极度单极吸附
            </div>
          </div>

          {/* 右侧: 乡镇空心化 */}
          <div
            style={{
              background: "linear-gradient(135deg, rgba(255, 255, 255, 0.12) 0%, rgba(15, 23, 42, 0.8) 100%)",
              backdropFilter: "blur(26px)",
              border: "1.5px solid rgba(255, 255, 255, 0.25)",
              borderRadius: 30,
              padding: "36px 20px",
              textAlign: "center",
              boxShadow: "0 15px 35px rgba(0, 0, 0, 0.3)",
            }}
          >
            <div style={{ fontSize: 24, color: "#CBD5E1", fontWeight: 700, marginBottom: 8 }}>
              周边乡村城镇
            </div>
            <div style={{ fontSize: 68, fontWeight: 900, color: "#94A3B8" }}>
              空心化
            </div>
            <div style={{ fontSize: 22, color: "#CBD5E1", marginTop: 8, fontWeight: 600 }}>
              青壮年持续流出
            </div>
          </div>
        </div>

        {/* 虹吸效应动态数据流条 (Siphon Stream Indicator) */}
        <div
          style={{
            width: "100%",
            background: "rgba(15, 23, 42, 0.7)",
            backdropFilter: "blur(20px)",
            borderRadius: 20,
            border: "1px solid rgba(244, 63, 94, 0.3)",
            padding: "12px 24px",
            marginBottom: 24,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontSize: 22, color: "#FDA4AF", fontWeight: 700 }}>
            ⚡ 虹吸流向: 乡村 ➔ 县城 ➔ 大湾区
          </span>
          <div style={{ display: "flex", gap: 6, transform: `translateX(${arrowOffset}px)` }}>
            <span style={{ color: "#F43F5E", fontWeight: 900 }}>➤</span>
            <span style={{ color: "#FB7185", fontWeight: 900 }}>➤</span>
            <span style={{ color: "#FDA4AF", fontWeight: 900 }}>➤</span>
          </div>
        </div>

        {/* 叙述卡片 */}
        <div
          style={{
            width: "100%",
            background: "linear-gradient(135deg, rgba(255, 255, 255, 0.12) 0%, rgba(15, 23, 42, 0.72) 100%)",
            backdropFilter: "blur(28px)",
            border: "1.5px solid rgba(255, 255, 255, 0.25)",
            borderRadius: 32,
            padding: "42px 38px",
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
