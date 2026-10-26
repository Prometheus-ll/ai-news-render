import React from 'react';
import {AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig, Easing} from 'remotion';

const bg = 'radial-gradient(ellipse 80% 45% at 50% 34%, #0e4a6b, #050b1a 70%)';
const font = 'Inter, Poppins, sans-serif';
// damping 200 = critically damped spring: lands softly, never bounces
const useArrive = (delay: number) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: f - delay, fps, config: {damping: 200}, durationInFrames: 24});
};
const Word: React.FC<{t: string; top: number; delay: number; hi?: boolean}> = ({t, top, delay, hi}) => {
  const p = useArrive(delay);
  return <div style={{position: 'absolute', left: 0, right: 0, top, textAlign: 'center', fontSize: 300, fontWeight: 900, textTransform: 'uppercase',
    color: hi ? '#22d3ee' : '#fff', opacity: p, transform: `scale(${1.14 - 0.14 * p})`, filter: `blur(${(1 - p) * 18}px)`}}>{t}</div>;
};
const Card: React.FC<{t: string; s: string; top: number; delay: number}> = ({t, s, top, delay}) => {
  const p = useArrive(delay);
  return <div style={{position: 'absolute', left: 110, right: 110, top, height: 210, borderRadius: 44, background: 'linear-gradient(135deg,#22d3ee,#3b6cf5)',
    display: 'flex', alignItems: 'center', padding: '0 60px', fontSize: 84, fontWeight: 900, color: '#fff', opacity: p,
    transform: `translateX(${-140 * (1 - p)}px)`, filter: `blur(${(1 - p) * 10}px)`}}>{t}<span style={{marginLeft: 'auto', fontSize: 34, fontWeight: 600}}>{s}</span></div>;
};
const S1 = () => {
  const p = useArrive(36);
  return <AbsoluteFill><Word t="No" top={420} delay={3} /><Word t="More" top={700} delay={11} /><Word t="Text" top={980} delay={19} hi />
    <div style={{position: 'absolute', left: 90, right: 90, top: 1380, textAlign: 'center', fontSize: 44, fontWeight: 600, color: '#fff', opacity: p,
      transform: `translateY(${50 * (1 - p)}px)`}}>OpenAI's new API only returns answers</div></AbsoluteFill>;
};
const S2 = () => <AbsoluteFill><Card t="Predicate" s="true or false" top={520} delay={4} /><Card t="Choice" s="pick one" top={790} delay={11} /><Card t="Score" s="rated" top={1060} delay={18} /></AbsoluteFill>;
const S3 = () => {
  const f = useCurrentFrame();
  const p = useArrive(4);
  const v = Math.round(interpolate(f, [4, 31], [0, 10], {extrapolateRight: 'clamp', easing: Easing.out(Easing.quad)}));
  const c = useArrive(30);
  return <AbsoluteFill><div style={{position: 'absolute', left: 0, right: 0, top: 640, textAlign: 'center', fontSize: 360, fontWeight: 900, color: '#22d3ee', opacity: p, filter: `blur(${(1 - p) * 14}px)`}}>{v}x</div>
    <div style={{position: 'absolute', left: 0, right: 0, top: 960, textAlign: 'center', fontSize: 52, fontWeight: 700, color: '#fff', opacity: c, transform: `translateY(${40 * (1 - c)}px)`}}>faster than the Responses API</div></AbsoluteFill>;
};
// blur swap between scenes: out fast (6 frames), in over 6 frames
const Scene: React.FC<{children: React.ReactNode; dur: number}> = ({children, dur}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [0, 6, dur - 6, dur], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const b = interpolate(f, [0, 6, dur - 6, dur], [9, 0, 0, 9], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <AbsoluteFill style={{opacity: o, filter: `blur(${b}px)`}}>{children}</AbsoluteFill>;
};
export const Main: React.FC = () => (
  <AbsoluteFill style={{background: bg, fontFamily: font}}>
    <Sequence from={0} durationInFrames={120}><Scene dur={120}><S1 /></Scene></Sequence>
    <Sequence from={120} durationInFrames={120}><Scene dur={120}><S2 /></Scene></Sequence>
    <Sequence from={240} durationInFrames={120}><Scene dur={120}><S3 /></Scene></Sequence>
  </AbsoluteFill>
);
