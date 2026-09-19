import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSearch, faFilter, faX } from '@fortawesome/free-solid-svg-icons';
import { api } from '../api/client';
import type { SearchHit, SearchResponse, Facets } from '../types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Separator } from '@/components/ui/separator';
import { Drawer, DrawerTrigger, DrawerContent, DrawerHeader, DrawerTitle, DrawerFooter } from '@/components/ui/drawer';
import MobileNavBar from '@/components/MobileNavBar';
import { useIsMobile } from '@/hooks/use-mobile';

const KIND_OPTIONS = [
  { value: 'transcript', label: 'Transcript' },
  { value: 'summary', label: 'Summary' },
  { value: 'decision', label: 'Decision' },
  { value: 'todo', label: 'Todo' },
];

const KIND_COLORS: Record<string, string> = {
  transcript: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  summary: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  decision: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  todo: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
};

const STATUS_OPTIONS = [
  { value: 'open', label: 'Open' },
  { value: 'done', label: 'Done' },
];

interface ActiveFilters {
  kind: string[];
  speaker: string[];
  status: string[];
  date_from: string;
  date_to: string;
  participants: string[];
}

const DEFAULT_FILTERS: ActiveFilters = {
  kind: [],
  speaker: [],
  status: [],
  date_from: '',
  date_to: '',
  participants: [],
};

function snippetAround(text: string, matchStart: number, contextChars = 100): string {
  const before = Math.max(0, matchStart - contextChars);
  const after = Math.min(text.length, matchStart + contextChars);
  const snippet = text.slice(before, after);
  return (before > 0 ? '…' : '') + snippet + (after < text.length ? '…' : '');
}

export default function SearchPage() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [searchParams, setSearchParams] = useSearchParams();

  const initialQuery = searchParams.get('q') || '';
  const [query, setQuery] = useState(initialQuery);
  const [inputValue, setInputValue] = useState(initialQuery);

  const [results, setResults] = useState<SearchResponse | null>(null);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [loading, setLoading] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [activeFilters, setActiveFilters] = useState<ActiveFilters>(DEFAULT_FILTERS);

  // Load facets on mount
  useEffect(() => {
    api.getSearchFacets().then(setFacets).catch(() => setFacets(null));
  }, []);

  const doSearch = useCallback(
    async (q: string, filters: ActiveFilters, offset = 0) => {
      if (!q.trim()) {
        setResults(null);
        return;
      }
      setLoading(true);
      try {
        const params: Parameters<typeof api.search>[0] = { q, limit: 20, offset };
        if (filters.kind.length === 1) params.kind = filters.kind[0];
        if (filters.status.length === 1) params.status = filters.status[0];
        if (filters.speaker.length > 0) params.speaker = filters.speaker.join(',');
        if (filters.date_from) params.date_from = filters.date_from;
        if (filters.date_to) params.date_to = filters.date_to;
        if (filters.participants.length > 0) params.participants = filters.participants.join(',');
        const data = await api.search(params);
        setResults(data);
      } catch {
        setResults(null);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  // Search on mount or when q/filter changes
  useEffect(() => {
    doSearch(query, activeFilters);
  }, [query, activeFilters, doSearch]);

  // Sync input when URL changes
  useEffect(() => {
    const urlQ = searchParams.get('q') || '';
    setInputValue(urlQ);
    setQuery(urlQ);
  }, [searchParams]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = inputValue.trim();
    setQuery(trimmed);
    setSearchParams(trimmed ? { q: trimmed } : {}, { replace: true });
  };

  const handleKindToggle = (value: string) => {
    setActiveFilters((f) => {
      const has = f.kind.includes(value);
      return { ...f, kind: has ? f.kind.filter((k) => k !== value) : [...f.kind, value] };
    });
  };

  const handleStatusToggle = (value: string) => {
    setActiveFilters((f) => {
      const has = f.status.includes(value);
      return { ...f, status: has ? f.status.filter((s) => s !== value) : [...f.status, value] };
    });
  };

  const handleSpeakerToggle = (value: string) => {
    setActiveFilters((f) => {
      const has = f.speaker.includes(value);
      return { ...f, speaker: has ? f.speaker.filter((s) => s !== value) : [...f.speaker, value] };
    });
  };

  const handleParticipantToggle = (value: string) => {
    setActiveFilters((f) => {
      const has = f.participants.includes(value);
      return { ...f, participants: has ? f.participants.filter((p) => p !== value) : [...f.participants, value] };
    });
  };

  const handleDateFromChange = (val: string) => setActiveFilters((f) => ({ ...f, date_from: val }));
  const handleDateToChange = (val: string) => setActiveFilters((f) => ({ ...f, date_to: val }));

  const removeFilter = (type: keyof ActiveFilters, value?: string) => {
    setActiveFilters((f) => {
      if (type === 'date_from' || type === 'date_to') return { ...f, [type]: '' };
      if (value === undefined) return { ...f, [type]: [] };
      return { ...f, [type]: (f[type] as string[]).filter((v) => v !== value) };
    });
  };

  const clearAll = () => setActiveFilters(DEFAULT_FILTERS);

  const hasActiveFilters =
    activeFilters.kind.length > 0 ||
    activeFilters.speaker.length > 0 ||
    activeFilters.status.length > 0 ||
    activeFilters.date_from !== '' ||
    activeFilters.date_to !== '' ||
    activeFilters.participants.length > 0;

  const chipItems: { label: string; onRemove: () => void }[] = [
    ...activeFilters.kind.map((v) => ({ label: KIND_OPTIONS.find((k) => k.value === v)?.label || v, onRemove: () => removeFilter('kind', v) })),
    ...activeFilters.status.map((v) => ({ label: STATUS_OPTIONS.find((s) => s.value === v)?.label || v, onRemove: () => removeFilter('status', v) })),
    ...activeFilters.speaker.map((v) => ({ label: v, onRemove: () => removeFilter('speaker', v) })),
    ...activeFilters.participants.map((v) => ({ label: v, onRemove: () => removeFilter('participants', v) })),
    ...(activeFilters.date_from || activeFilters.date_to
      ? [{ label: `${activeFilters.date_from || '…'} – ${activeFilters.date_to || '…'}`, onRemove: () => { removeFilter('date_from'); removeFilter('date_to'); } }]
      : []),
  ];

  const FilterPanel = ({ onClose }: { onClose?: () => void }) => (
    <div className="flex flex-col gap-4 p-4">
      {onClose && (
        <div className="flex items-center justify-between">
          <span className="font-semibold">Filters</span>
          <Button variant="ghost" size="sm" onClick={onClose} className="h-8 px-2">
            <FontAwesomeIcon icon={faX} />
          </Button>
        </div>
      )}

      {/* Kind */}
      <div>
        <p className="text-sm font-medium mb-2">Kind</p>
        <div className="flex flex-col gap-1">
          {KIND_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 cursor-pointer">
              <Checkbox
                checked={activeFilters.kind.includes(opt.value)}
                onCheckedChange={() => handleKindToggle(opt.value)}
              />
              <span className="text-sm">{opt.label}</span>
            </label>
          ))}
        </div>
      </div>

      <Separator />

      {/* Status (applies to todos) */}
      <div>
        <p className="text-sm font-medium mb-2">Status</p>
        <div className="flex flex-col gap-1">
          {STATUS_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 cursor-pointer">
              <Checkbox
                checked={activeFilters.status.includes(opt.value)}
                onCheckedChange={() => handleStatusToggle(opt.value)}
              />
              <span className="text-sm">{opt.label}</span>
            </label>
          ))}
        </div>
      </div>

      <Separator />

      {/* Date Range */}
      <div>
        <p className="text-sm font-medium mb-2">Date Range</p>
        <div className="flex gap-2 items-center">
          <Input
            type="date"
            value={activeFilters.date_from}
            onChange={(e) => handleDateFromChange(e.target.value)}
            className="flex-1"
          />
          <span>–</span>
          <Input
            type="date"
            value={activeFilters.date_to}
            onChange={(e) => handleDateToChange(e.target.value)}
            className="flex-1"
          />
        </div>
      </div>

      <Separator />

      {/* Speakers */}
      {facets && facets.speakers.length > 0 && (
        <>
          <div>
            <p className="text-sm font-medium mb-2">Speakers</p>
            <div className="flex flex-col gap-1 max-h-40 overflow-y-auto">
              {facets.speakers.filter(Boolean).map((speaker) => (
                <label key={speaker} className="flex items-center gap-2 cursor-pointer">
                  <Checkbox
                    checked={activeFilters.speaker.includes(speaker)}
                    onCheckedChange={() => handleSpeakerToggle(speaker)}
                  />
                  <span className="text-sm">{speaker}</span>
                </label>
              ))}
            </div>
          </div>
          <Separator />
        </>
      )}

      {/* Participants */}
      {facets && facets.participants.length > 0 && (
        <>
          <div>
            <p className="text-sm font-medium mb-2">Participants</p>
            <div className="flex flex-col gap-1 max-h-40 overflow-y-auto">
              {facets.participants.filter(Boolean).map((p) => (
                <label key={p} className="flex items-center gap-2 cursor-pointer">
                  <Checkbox
                    checked={activeFilters.participants.includes(p)}
                    onCheckedChange={() => handleParticipantToggle(p)}
                  />
                  <span className="text-sm">{p}</span>
                </label>
              ))}
            </div>
          </div>
          <Separator />
        </>
      )}

      {onClose && (
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="flex-1" onClick={clearAll}>
            Clear All
          </Button>
          <Button size="sm" className="flex-1" onClick={onClose}>
            Apply Filters
          </Button>
        </div>
      )}
    </div>
  );

  return (
    <div className="flex flex-col min-h-screen">
      {/* Desktop header bar */}
      <div className="border-b bg-background px-4 py-3">
        <form onSubmit={handleSearchSubmit} className="flex gap-2 max-w-2xl mx-auto">
          <div className="relative flex-1">
            <FontAwesomeIcon
              icon={faSearch}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Search conversations, summaries, decisions, todos…"
              className="pl-9"
              autoFocus
            />
          </div>
          <Button type="submit" size="sm">
            Search
          </Button>
          {isMobile && (
            <Drawer open={filtersOpen} onOpenChange={setFiltersOpen}>
              <DrawerTrigger asChild>
                <Button variant="outline" size="sm" className="relative">
                  <FontAwesomeIcon icon={faFilter} />
                  {hasActiveFilters && (
                    <span className="absolute -top-1 -right-1 h-4 w-4 rounded-full bg-primary text-primary-foreground text-xs flex items-center justify-center">
                      {chipItems.length}
                    </span>
                  )}
                </Button>
              </DrawerTrigger>
              <DrawerContent>
                <DrawerHeader>
                  <DrawerTitle>Filters</DrawerTitle>
                </DrawerHeader>
                <FilterPanel />
                <DrawerFooter>
                  <Button onClick={() => setFiltersOpen(false)}>Apply</Button>
                </DrawerFooter>
              </DrawerContent>
            </Drawer>
          )}
        </form>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Desktop sidebar */}
        {!isMobile && (
          <aside className="w-64 border-r overflow-y-auto shrink-0 bg-background">
            <div className="p-4">
              <div className="flex items-center justify-between mb-4">
                <span className="font-semibold">Filters</span>
                {hasActiveFilters && (
                  <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={clearAll}>
                    Clear
                  </Button>
                )}
              </div>
              <FilterPanel />
            </div>
          </aside>
        )}

        {/* Main content */}
        <main className="flex-1 overflow-y-auto p-4">
          {/* Active filter chips */}
          {chipItems.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-4">
              {chipItems.map((chip) => (
                <button
                  key={chip.label}
                  onClick={chip.onRemove}
                  className="flex items-center gap-1 px-3 py-1 rounded-full bg-primary/10 text-primary text-sm hover:bg-primary/20 transition-colors"
                >
                  {chip.label}
                  <FontAwesomeIcon icon={faX} className="h-3 w-3" />
                </button>
              ))}
            </div>
          )}

          {/* Results */}
          {loading && (
            <div className="flex flex-col gap-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="animate-pulse rounded border p-4 space-y-2">
                  <div className="h-4 bg-muted rounded w-1/4" />
                  <div className="h-3 bg-muted rounded w-3/4" />
                  <div className="h-3 bg-muted rounded w-1/2" />
                </div>
              ))}
            </div>
          )}

          {!loading && !results && query && (
            <div className="text-center py-12 text-muted-foreground">
              <p className="text-lg">No results for &ldquo;{query}&rdquo;</p>
              <p className="text-sm mt-1">Try different keywords or remove filters.</p>
            </div>
          )}

          {!loading && !query && (
            <div className="text-center py-12 text-muted-foreground">
              <FontAwesomeIcon icon={faSearch} className="h-12 w-12 mb-4 opacity-30" />
              <p className="text-lg">Search your conversations</p>
              <p className="text-sm mt-1">Find transcript turns, summaries, decisions, and todos.</p>
            </div>
          )}

          {!loading && results && results.hits.length === 0 && (
            <div className="text-center py-12 text-muted-foreground">
              <p className="text-lg">No results for &ldquo;{query}&rdquo;</p>
              <p className="text-sm mt-1">Try different keywords or remove filters.</p>
            </div>
          )}

          {!loading && results && results.hits.length > 0 && (
            <div className="flex flex-col gap-3">
              {results.hits.map((hit) => (
                <SearchHitCard
                  key={hit.id}
                  hit={hit}
                  onNavigate={() => {
                    const params = new URLSearchParams({ q: query });
                    if (hit._matchesPosition) {
                      params.set('matches', btoa(JSON.stringify(hit._matchesPosition)));
                    }
                    navigate(`/recording/${hit.conversation_id}?${params}`);
                  }}
                />
              ))}

              {/* Load more */}
              {results.offset + results.hits.length < results.total && (
                <div className="flex justify-center pt-2">
                  <Button
                    variant="outline"
                    onClick={() => doSearch(query, activeFilters, results!.offset + results!.limit)}
                    disabled={loading}
                  >
                    Load more
                  </Button>
                </div>
              )}

              <p className="text-xs text-muted-foreground text-center">
                {results.total} result{results.total !== 1 ? 's' : ''} · {results.processingTimeMs}ms
              </p>
            </div>
          )}
        </main>
      </div>

      <MobileNavBar />
    </div>
  );
}

function SearchHitCard({
  hit,
  onNavigate,
}: {
  hit: SearchHit;
  onNavigate: () => void;
}) {
  const kindLabel = KIND_OPTIONS.find((k) => k.value === hit.kind)?.label || hit.kind;
  const kindColorClass = KIND_COLORS[hit.kind] || 'bg-gray-100 text-gray-800';

  const matches = hit._matchesPosition;

  // Find first match position for snippet
  let snippet = hit.text.slice(0, 200);
  if (hit.text.length > 200) snippet += '…';
  if (matches?.['text'] && matches['text'].length > 0) {
    const firstMatch = matches['text'][0];
    snippet = snippetAround(hit.text, firstMatch.start);
  }

  return (
    <div
      className="rounded border p-4 cursor-pointer hover:shadow-md transition-shadow bg-card"
      onClick={onNavigate}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onNavigate()}
    >
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${kindColorClass}`}>
          {kindLabel}
        </span>
        {hit.title && (
          <span className="font-semibold text-sm">{hit.title}</span>
        )}
        {hit.date && (
          <span className="text-xs text-muted-foreground">{hit.date}</span>
        )}
        {hit.speaker && (
          <span className="text-xs text-muted-foreground">· {hit.speaker}</span>
        )}
      </div>
      <p className="text-sm text-foreground mb-1">{snippet}</p>
      {hit.status && (
        <p className="text-xs text-muted-foreground">Status: {hit.status}</p>
      )}
    </div>
  );
}
