import { useRef, useState } from 'react';
import type { Speaker } from '../types';

interface AudioPlayerProps {
  src: string;
  segments: Speaker[];
}

export default function AudioPlayer({ src, segments }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  const handleTimeUpdate = () => {
    setCurrentTime(audioRef.current?.currentTime || 0);
  };

  const togglePlay = () => {
    if (isPlaying) {
      audioRef.current?.pause();
    } else {
      audioRef.current?.play();
    }
    setIsPlaying(!isPlaying);
  };

  const seekTo = (time: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = time;
    }
  };

  const getCurrentSpeaker = (): Speaker | undefined => {
    return segments.find((s) => currentTime >= s.start && currentTime <= s.end);
  };

  const currentSpeaker = getCurrentSpeaker();
  const maxEnd = segments.length > 0 ? Math.max(...segments.map((s) => s.end)) : 1;

  return (
    <div className="audio-player">
      <audio ref={audioRef} src={src} onTimeUpdate={handleTimeUpdate} />

      <button onClick={togglePlay}>{isPlaying ? 'Pause' : 'Play'}</button>

      <div className="timeline">
        {segments.map((segment, i) => (
          <div
            key={i}
            className={`segment ${segment.name === 'Unknown' ? 'unknown' : ''}`}
            style={{
              left: `${(segment.start / maxEnd) * 100}%`,
              width: `${((segment.end - segment.start) / maxEnd) * 100}%`,
            }}
            onClick={() => seekTo(segment.start)}
            title={`${segment.name}: ${segment.start.toFixed(1)}s - ${segment.end.toFixed(1)}s`}
          />
        ))}
      </div>

      {currentSpeaker && (
        <div className="current-speaker">Currently: {currentSpeaker.name}</div>
      )}
    </div>
  );
}
