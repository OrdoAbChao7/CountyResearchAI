import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";

interface AtmosphereLayerProps {
  themeColor: "amber" | "blue" | "rose" | "gold" | "emerald";
}

const THEME_GRADIENTS: Record<string, { primary: string; secondary: string }> = {
  amber: {
    primary: "rgba(245, 158, 11, 0.25)",
    secondary: "rgba(217, 119, 6, 0.15)",
  },
  blue: {
    primary: "rgba(59, 130, 246, 0.25)",
    secondary: "rgba(14, 165, 233, 0.15)",
  },
  rose: {
    primary: "rgba(244, 63, 94, 0.25)",
    secondary: "rgba(225, 29, 72, 0.15)",
  },
  gold: {
    primary: "rgba(251, 191, 36, 0.3)",
    secondary: "rgba(217, 119, 6, 0.2)",
  },
  emerald: {
    primary: "rgba(16, 185, 129, 0.25)",
    secondary: "rgba(5, 150, 105, 0.15)",
  },
};

export const AtmosphereLayer: React.FC<AtmosphereLayerProps> = ({ themeColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const theme = THEME_GRADIENTS[themeColor] || THEME_GRADIENTS.amber;

  // 缓慢漂浮的光晕呼吸动效
  const pulse1 = Math.sin((frame / fps) * 1.2) * 0.08 + 1.0;
  const pulse2 = Math.cos((frame / fps) * 0.9) * 0.06 + 1.0;

  // 电影级丁达尔光柱 (Volumetric God Rays) 扫光旋转动效
  const rayAngle = interpolate(frame % 180, [0, 180], [-25, -15]);
  const rayOpacity = 0.18 + Math.sin((frame / fps) * 0.8) * 0.08;

  // 缓慢漂浮的微光粒子 (计算 6 个环境光斑)
  const particles = [
    { x: 200, y: 400, size: 280, speed: 0.8 },
    { x: 800, y: 700, size: 320, speed: 1.1 },
    { x: 300, y: 1200, size: 260, speed: 0.9 },
    { x: 750, y: 1500, size: 300, speed: 1.0 },
  ];

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        pointerEvents: "none",
        zIndex: 1,
      }}
    >
      {/* 丁达尔神光光柱 (Volumetric God Ray) */}
      <div
        style={{
          position: "absolute",
          top: -200,
          left: -100,
          width: 800,
          height: 1800,
          background: `linear-gradient(${rayAngle}deg, ${theme.primary} 0%, rgba(255,255,255,0.06) 40%, rgba(0,0,0,0) 80%)`,
          opacity: rayOpacity,
          filter: "blur(50px)",
          transformOrigin: "top left",
        }}
      />

      {/* 顶部环境光弧 */}
      <div
        style={{
          position: "absolute",
          top: -150,
          left: "50%",
          width: 900,
          height: 600,
          marginLeft: -450,
          borderRadius: "50%",
          background: `radial-gradient(ellipse, ${theme.primary} 0%, rgba(0,0,0,0) 70%)`,
          transform: `scale(${pulse1})`,
          filter: "blur(60px)",
        }}
      />

      {/* 底部暖光映衬 */}
      <div
        style={{
          position: "absolute",
          bottom: -100,
          right: -100,
          width: 700,
          height: 500,
          borderRadius: "50%",
          background: `radial-gradient(ellipse, ${theme.secondary} 0%, rgba(0,0,0,0) 75%)`,
          transform: `scale(${pulse2})`,
          filter: "blur(70px)",
        }}
      />

      {/* 漂浮微光粒子 */}
      {particles.map((p, i) => {
        const offsetY = Math.sin((frame / fps) * p.speed + i) * 30;
        const offsetX = Math.cos((frame / fps) * p.speed + i) * 20;

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: p.x + offsetX,
              top: p.y + offsetY,
              width: p.size,
              height: p.size,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${theme.primary} 0%, rgba(0,0,0,0) 70%)`,
              opacity: 0.6,
              filter: "blur(40px)",
            }}
          />
        );
      })}
    </div>
  );
};
