import React from 'react';
import {Composition} from 'remotion';
import {Main} from './Main';
export const Root: React.FC = () => (
  <Composition id="Main" component={Main} durationInFrames={360} fps={30} width={1080} height={1920} />
);
