import React from "react";
import { Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

interface BackgroundMediaProps {
  imageUrl?: string;
}

export const BackgroundMedia: React.FC<BackgroundMediaProps> = ({ imageUrl }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  if (!imageUrl) {
    return null;
  }

  // 电影感慢速推拉运镜 (Ken Burns Effect)
  const zoom = interpolate(frame, [0, durationInFrames || fps * 15], [1.0, 1.12], {
    extrapolateRight: "clamp",
  });

  const src =
    imageUrl.startsWith("http://") ||
    imageUrl.startsWith("https://") ||
    imageUrl.startsWith("data:")
      ? imageUrl
      : staticFile(imageUrl);

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        zIndex: 0,
        pointerEvents: "none",
      }}
    >
      {/* 背景大图 + 运镜 + 电影色彩增强 (明度从 0.32 提升至 0.68，消除压抑死黑感) */}
      <Img
        src={src}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${zoom})`,
          filter: "brightness(0.68) contrast(1.1) saturate(1.2)",
        }}
      />

      {/* 柔和透光电影暗角 (保留景深与光影层次，配合前景毛玻璃卡片) */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(180deg, rgba(15,23,42,0.40) 0%, rgba(15,23,42,0.25) 45%, rgba(15,23,42,0.75) 100%)",
        }}
      />
    </div>
  );
};
