import { useRef, useState, useEffect } from 'react';
import type { Speaker } from '../types';

interface AudioPlayerProps {
  src?: string;
  segments: Speaker[];
  sources?: string[];
}

export default function AudioPlayer({ src, segments, sources }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [sourceIndex, setSourceIndex] = useState(0);

  // Build the effective list of sources
  const allSources = sources && sources.length > 0 ? sources : src ? [src] : [];

  useEffect(() => {
    // Reset when sources change
    setSourceIndex(0);
    setCurrentTime(0);
    setIsPlaying(false);
  }, [sources?.join(','), src]);

  const handleTimeUpdate = () => {
    setCurrentTime(audioRef.current?.currentTime || 0);
  };

  const handleEnded = () => {
    // Auto-advance to next source
    if (sourceIndex < allSources.length - 1) {
      setSourceIndex(sourceIndex + 1);
      // Auto-play next on load
      setTimeout(() => {
        audioRef.current?.play();
      }, 100);
    } else {
      setIsPlaying(false);
    }
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

  if (allSources.length === 0) return null;

  return (
    <div className="audio-player">
      <audio
        ref={audioRef}
        src={allSources[sourceIndex]}
        onTimeUpdate={handleTimeUpdate}
        onEnded={handleEnded}
      />

      <button onClick={togglePlay}>{isPlaying ? 'Pause' : 'Play'}</button>
      {allSources.length > 1 && (
        <span className="source-indicator">
          Part {sourceIndex + 1} of {allSources.length}
        </span>
      )}

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
