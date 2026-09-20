import React from "react";
import { Composition } from "remotion";
import { CountyVideo } from "./CountyVideo";
import { VideoProps } from "./types";

const defaultProps: VideoProps = {
  county: "信丰县",
  title: "高铁穿过,人口却走了:信丰的交通悖论",
  hook: "赣深高铁穿境而过,信丰的年轻人却依然在流向广东。",
  perspective: "从'交通改善但人口流失'这一悖论切入",
  total_duration_ms: 44000,
  audio_url: "",
  segments: [
    {
      segment_id: "hook",
      time_range: "0-5s",
      narration: "赣深高铁穿境而过,信丰的年轻人却依然在流向广东。",
      on_screen: "信丰 · 交通悖论",
      visual_hint: "高铁飞驰画面与县城冷清街道快速切换",
      duration_ms: 5600,
      start_offset_ms: 0,
      end_offset_ms: 5600,
      image_url: "images/seg_0_hook.jpg",
    },
    {
      segment_id: "origin",
      time_range: "5-20s",
      narration: "信丰自古因赣粤驿道而兴,是南北商贸的必经之地。交通,一直是这座县城兴衰的关键变量。",
      on_screen: "赣粤驿道 · 千年商路",
      visual_hint: "古代驿道地图与商队行进的历史插画",
      duration_ms: 8900,
      start_offset_ms: 5600,
      end_offset_ms: 14500,
      image_url: "images/seg_1_origin.jpg",
    },
    {
      segment_id: "growth",
      time_range: "20-40s",
      narration: "新世纪以来,高速、高铁相继开通,区位优势看似更明显了。但数据显示,户籍与常住人口差额估计达5到8万人。",
      on_screen: "人口差额 5-8 万",
      visual_hint: "高速公路与高铁线路图叠加,随后切换至人口外流趋势图",
      duration_ms: 11400,
      start_offset_ms: 14500,
      end_offset_ms: 25900,
      image_url: "images/seg_2_growth.jpg",
    },
    {
      segment_id: "decline",
      time_range: "40-55s",
      narration: "县城单极集中,嘉定镇占全县人口37%以上,乡镇空心化明显。交通越便利,人反而越容易离开。",
      on_screen: "嘉定镇人口占比 37%+",
      visual_hint: "信丰县地图上嘉定镇高亮,周边乡镇逐渐暗淡",
      duration_ms: 10900,
      start_offset_ms: 25900,
      end_offset_ms: 36800,
      image_url: "images/seg_3_decline.jpg",
    },
    {
      segment_id: "takeaway",
      time_range: "55-60s",
      narration: "区位优势若没有产业承接,就只是过路经济。交通是通道,不是终点。",
      on_screen: "过路经济 vs 落地经济",
      visual_hint: "高铁站台人流匆匆,无人停留的意象画面",
      duration_ms: 7200,
      start_offset_ms: 36800,
      end_offset_ms: 44000,
      image_url: "images/seg_4_takeaway.jpg",
    },
  ],
  subtitles: [],
};

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="CountyVideo"
        component={CountyVideo}
        durationInFrames={1350} // 45s * 30fps
        fps={30}
        width={1080}
        height={1920}
        defaultProps={defaultProps}
        calculateMetadata={async ({ props }) => {
          const fps = 30;
          let totalFrames = 0;
          if (props.segments && props.segments.length > 0) {
            for (const seg of props.segments) {
              const dur = Math.max(Math.round((seg.duration_ms / 1000) * fps), fps * 2);
              totalFrames += dur;
            }
          } else if (props.total_duration_ms) {
            totalFrames = Math.ceil((props.total_duration_ms / 1000) * fps);
          } else {
            totalFrames = 1350;
          }
          return {
            durationInFrames: Math.max(totalFrames, 300),
          };
        }}
      />
    </>
  );
};
