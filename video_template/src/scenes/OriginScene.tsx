import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { AtmosphereLayer } from "../components/AtmosphereLayer";
import { BackgroundMedia } from "../components/BackgroundMedia";
import { Header } from "../components/Header";
import { SegmentProp } from "../types";

interface OriginSceneProps {
  county: string;
  segment: SegmentProp;
}

export const OriginScene: React.FC<OriginSceneProps> = ({ county, segment }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 100 },
  });

  // 时间轴光线延展动效
  const timelineProgress = interpolate(frame, [10, 40], [0, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const tiltX = Math.sin((frame / fps) * 1.3) * 2.0;
  const tiltY = Math.cos((frame / fps) * 1.1) * 2.5;

  const timelineNodes = [
    { era: "唐宋", title: "赣粤古驿道", desc: "水陆咽喉", active: false },
    { era: "1996", title: "京九铁路", desc: "南北大干线", active: false },
    { era: "2021", title: "赣深高铁", desc: "双刃剑重构", active: true },
  ];

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
      <AtmosphereLayer themeColor="emerald" />
      <Header county={county} category="历史源流 · 02" chapterIndex={1} />

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
        {/* 屏幕核心标签 */}
        <div
          style={{
            background: "linear-gradient(90deg, #10B981 0%, #059669 100%)",
            color: "#FFFFFF",
            padding: "12px 36px",
            borderRadius: 30,
            fontSize: 28,
            fontWeight: 800,
            letterSpacing: 2,
            marginBottom: 28,
            boxShadow: "0 6px 25px rgba(16, 185, 129, 0.4)",
            border: "1px solid rgba(255, 255, 255, 0.25)",
            transform: `scale(${progress})`,
          }}
        >
          📜 {segment.on_screen || "历史变迁"}
        </div>

        <h2
          style={{
            fontSize: 58,
            fontWeight: 900,
            color: "#FFFFFF",
            textAlign: "center",
            lineHeight: 1.3,
            margin: "0 0 32px 0",
            textShadow: "0 6px 25px rgba(0,0,0,0.8)",
            transform: `scale(${progress})`,
          }}
        >
          千年商路与区位重构
        </h2>

        {/* 3 节点历史时间轴卡片 */}
        <div
          style={{
            width: "100%",
            background: "rgba(15, 23, 42, 0.65)",
            backdropFilter: "blur(24px)",
            borderRadius: 28,
            border: "1px solid rgba(16, 185, 129, 0.3)",
            padding: "24px 28px",
            marginBottom: 30,
            position: "relative",
            boxShadow: "0 15px 35px rgba(0,0,0,0.4)",
          }}
        >
          {/* 背景贯穿光线 */}
          <div
            style={{
              position: "absolute",
              top: 52,
              left: 60,
              right: 60,
              height: 4,
              background: "rgba(255, 255, 255, 0.15)",
              borderRadius: 2,
            }}
          >
            <div
              style={{
                width: `${timelineProgress}%`,
                height: "100%",
                background: "linear-gradient(90deg, #10B981 0%, #34D399 100%)",
                boxShadow: "0 0 10px rgba(52, 211, 153, 0.8)",
                borderRadius: 2,
              }}
            />
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr",
              position: "relative",
              zIndex: 2,
            }}
          >
            {timelineNodes.map((node, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  textAlign: "center",
                }}
              >
                <div
                  style={{
                    width: 38,
                    height: 38,
                    borderRadius: 19,
                    background: node.active
                      ? "linear-gradient(135deg, #10B981 0%, #059669 100%)"
                      : "rgba(30, 41, 59, 0.9)",
                    border: node.active
                      ? "3px solid #6EE7B7"
                      : "2px solid rgba(255, 255, 255, 0.3)",
                    boxShadow: node.active
                      ? "0 0 16px rgba(16, 185, 129, 0.8)"
                      : "none",
                    marginBottom: 12,
                  }}
                />
                <div
                  style={{
                    fontSize: 22,
                    fontWeight: 800,
                    color: node.active ? "#6EE7B7" : "#94A3B8",
                  }}
                >
                  {node.era}
                </div>
                <div
                  style={{
                    fontSize: 24,
                    fontWeight: 800,
                    color: node.active ? "#FFFFFF" : "#CBD5E1",
                    marginTop: 2,
                  }}
                >
                  {node.title}
                </div>
                <div
                  style={{
                    fontSize: 18,
                    color: "#64748B",
                    marginTop: 4,
                  }}
                >
                  {node.desc}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 历史叙述卡片 */}
        <div
          style={{
            width: "100%",
            background: "linear-gradient(135deg, rgba(255, 255, 255, 0.14) 0%, rgba(15, 23, 42, 0.76) 100%)",
            backdropFilter: "blur(30px)",
            border: "1.5px solid rgba(255, 255, 255, 0.28)",
            borderRadius: 36,
            padding: "46px 42px",
            boxShadow: "0 25px 60px rgba(0,0,0,0.55), inset 0 1px 2px rgba(255,255,255,0.3)",
            transform: `scale(${0.94 + progress * 0.06}) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`,
            opacity: progress,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
            <div
              style={{
                width: 50,
                height: 50,
                borderRadius: 25,
                background: "linear-gradient(135deg, #10B981 0%, #059669 100%)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 26,
                boxShadow: "0 4px 15px rgba(16, 185, 129, 0.4)",
              }}
            >
              🏛️
            </div>
            <div style={{ fontSize: 32, fontWeight: 800, color: "#6EE7B7" }}>
              历史逻辑 · 变迁轨迹
            </div>
          </div>

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

          <div
            style={{
              marginTop: 36,
              paddingTop: 24,
              borderTop: "1px solid rgba(255,255,255,0.15)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span style={{ fontSize: 24, color: "#93C5FD", fontWeight: 600 }}>
              💡 关键启示: 交通区位随技术迭代而重估
            </span>
            <span
              style={{
                fontSize: 20,
                color: "#6EE7B7",
                background: "rgba(16, 185, 129, 0.18)",
                padding: "6px 14px",
                borderRadius: 12,
                border: "1px solid rgba(16, 185, 129, 0.4)",
                fontWeight: 700,
              }}
            >
              县志考据 ✓
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
