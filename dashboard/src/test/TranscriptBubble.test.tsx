import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import TranscriptBubble from "../components/TranscriptBubble";
import type { TranscriptSegment } from "../types";

describe("TranscriptBubble", () => {
  const segments: TranscriptSegment[] = [
    { speaker: "Alice", text: "First message" },
    { speaker: "Alice", text: "Second message" },
    { speaker: "Bob", text: "Third message" },
    { speaker: "Alice", text: "Fourth message" },
    { speaker: "Alice", text: "Fifth message" },
    { speaker: "Alice", text: "Sixth message" },
  ];

  it("renders all segments (consecutive same-speaker merged into one bubble)", () => {
    render(<TranscriptBubble segments={segments} />);
    // Consecutive same-speaker utterances are joined into one bubble per group
    expect(screen.getAllByText(/First message Second message/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Third message/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Fourth message Fifth message Sixth message/).length).toBeGreaterThan(0);
  });

  it("shows speaker label once per group", () => {
    render(<TranscriptBubble segments={segments} />);
    // Alice has 2 groups (merged): [First+Second], [Fourth+Fifth+Sixth], Bob has 1
    const aliceLabels = screen.getAllByText("Alice");
    expect(aliceLabels).toHaveLength(2);
    expect(screen.getByText("Bob")).toBeInTheDocument();
  });

  it("uses speakerLabel prop to transform label", () => {
    render(
      <TranscriptBubble
        segments={[{ speaker: "X", text: "Hi" }]}
        speakerLabel={(n) => `Speaker: ${n}`}
      />
    );
    expect(screen.getByText("Speaker: X")).toBeInTheDocument();
  });

  it("handles single segment", () => {
    render(
      <TranscriptBubble segments={[{ speaker: "Solo", text: "Only one" }]} />
    );
    expect(screen.getByText("Only one")).toBeInTheDocument();
    expect(screen.getByText("Solo")).toBeInTheDocument();
  });

  it("handles unknown speaker", () => {
    render(<TranscriptBubble segments={[{ text: "No speaker info" }]} />);
    expect(screen.getByText("No speaker info")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("hides speaker labels when hideSpeakerLabels is true", () => {
    render(
      <TranscriptBubble
        segments={[
          { speaker: "Alice", text: "Hello" },
          { speaker: "Alice", text: "World" },
        ]}
        hideSpeakerLabels
      />
    );
    // Consecutive Alice segments are merged into one bubble
    expect(screen.getAllByText(/Hello World/).length).toBeGreaterThan(0);
    expect(screen.queryByText("Alice")).not.toBeInTheDocument();
  });
});
