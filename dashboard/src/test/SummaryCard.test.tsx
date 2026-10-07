import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import SummaryCard from "../components/SummaryCard";

describe("SummaryCard", () => {
  it("renders the summary heading", () => {
    render(<SummaryCard markdown="This is a summary." />);
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Summary");
  });

  it("renders plain markdown as text", () => {
    render(<SummaryCard markdown="This is a **bold** statement." />);
    expect(screen.getAllByText(/statement\./)[0]).toBeInTheDocument();
  });

  it("renders headings", () => {
    render(<SummaryCard markdown="# Heading\n\nParagraph text." />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Heading");
  });

  it("renders bullet lists", () => {
    render(<SummaryCard markdown="- item one\n- item two" />);
    expect(screen.getAllByText(/item one/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/item two/).length).toBeGreaterThan(0);
  });

  it("renders numbered lists", () => {
    render(<SummaryCard markdown="1. first\n2. second" />);
    expect(screen.getAllByText(/first/)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/second/)[0]).toBeInTheDocument();
  });

  it("renders inline code", () => {
    render(<SummaryCard markdown="Use `console.log()` for debugging." />);
    expect(screen.getAllByText(/console\.log/)[0]).toBeInTheDocument();
  });

  it("renders code blocks", () => {
    render(<SummaryCard markdown="```\nconst x = 1;\n```" />);
    expect(screen.getAllByText(/const x = 1/)[0]).toBeInTheDocument();
  });

  it("renders blockquotes", () => {
    render(<SummaryCard markdown="> This is a quote" />);
    expect(screen.getAllByText(/quote/)[0]).toBeInTheDocument();
  });

  it("renders tables (GFM)", () => {
    render(<SummaryCard markdown="| Col1 | Col2 |\n|------|------|\n| A    | B    |" />);
    expect(screen.getAllByText(/Col1/)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/A/)[0]).toBeInTheDocument();
  });

  it("renders strikethrough (GFM)", () => {
    render(<SummaryCard markdown="~~deleted~~ text" />);
    expect(document.body.querySelector("del")).toBeInTheDocument();
  });

  it("renders bold and italic", () => {
    render(<SummaryCard markdown="**bold** and *italic*" />);
    const strong = document.body.querySelector("strong");
    const em = document.body.querySelector("em");
    expect(strong).toHaveTextContent("bold");
    expect(em).toHaveTextContent("italic");
  });

  it("applies [[hilite]] markers as <mark> elements", () => {
    render(<SummaryCard markdown="This has [[hilite]]important[[/hilite]] text." />);
    const marks = document.body.querySelectorAll("mark");
    expect(marks).toHaveLength(1);
    expect(marks[0]).toHaveTextContent("important");
  });
});
