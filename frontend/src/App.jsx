import { useCallback, useEffect, useMemo, useState } from "react";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000";

const DEFAULT_SETTINGS = Object.freeze({
  query: "Full Stack Backend Software Engineer in Bangalore",
  country: "in",
  language: "en",
  datePosted: "month",
  maxResults: 100,
  cities: "bangalore\nbengaluru",
  roles: [
    "full stack engineer",
    "software engineer",
    "software developer",
    "backend engineer",
    "backend developer",
    "software",
  ].join("\n"),
});

function readStoredSettings() {
  try {
    const stored = JSON.parse(localStorage.getItem("job-scout-settings-v2"));
    return stored && typeof stored === "object"
      ? { ...DEFAULT_SETTINGS, ...stored }
      : { ...DEFAULT_SETTINGS };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

function splitLines(value) {
  return [...new Set(value.split("\n").map((item) => item.trim()).filter(Boolean))];
}

function buildFetchPath(settings) {
  const params = new URLSearchParams({
    query: settings.query.trim(),
    country: settings.country.trim().toLowerCase(),
    language: settings.language.trim().toLowerCase(),
    date_posted: settings.datePosted,
    max_results: String(settings.maxResults),
  });
  splitLines(settings.cities).forEach((city) => params.append("city", city));
  splitLines(settings.roles).forEach((role) => params.append("role", role));
  return `/fetch-jobs?${params.toString()}`;
}

async function request(path) {
  const response = await fetch(`${API_BASE_URL}${path}`);
  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(payload?.detail || "The job service could not complete the request.");
  }
  return payload;
}

function downloadJson(jobs, filenamePrefix) {
  const timestamp = new Date().toISOString().replaceAll(":", "-");
  const blob = new Blob([`${JSON.stringify(jobs, null, 2)}\n`], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${filenamePrefix}-${timestamp}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function JobCard({ job }) {
  let safeApplyLink = null;
  try {
    const parsedLink = new URL(job.job_apply_link);
    if (["http:", "https:"].includes(parsedLink.protocol)) {
      safeApplyLink = parsedLink.href;
    }
  } catch {
    safeApplyLink = null;
  }

  const fetchedLabel = new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(job.fetched_at));

  return (
    <article className="job-card">
      <div className="job-card__copy">
        <p className="employer">{job.employer_name || "Employer not listed"}</p>
        <h3>{job.job_title}</h3>
        <p className="fetched-at">Fetched {fetchedLabel}</p>
      </div>
      {safeApplyLink ? (
        <a
          className="apply-link"
          href={safeApplyLink}
          target="_blank"
          rel="noreferrer"
        >
          View job <span aria-hidden="true">→</span>
        </a>
      ) : (
        <span className="link-unavailable">Link unavailable</span>
      )}
    </article>
  );
}

function EmptyState({ children }) {
  return <div className="empty-state">{children}</div>;
}

function SearchSettings({ settings, onChange, onReset }) {
  function update(field, value) {
    onChange((current) => ({ ...current, [field]: value }));
  }

  return (
    <details className="settings-panel">
      <summary>
        <span>
          <strong>Search settings</strong>
          <small>Adjust the JSearch request and strict client-side filters</small>
        </span>
        <span className="settings-chevron" aria-hidden="true">⌄</span>
      </summary>

      <div className="settings-body">
        <label className="field field-wide">
          <span>Search query</span>
          <input
            value={settings.query}
            onChange={(event) => update("query", event.target.value)}
            minLength={2}
            maxLength={200}
            required
          />
        </label>

        <div className="settings-row settings-row-four">
          <label className="field">
            <span>Country code</span>
            <input
              value={settings.country}
              onChange={(event) => update("country", event.target.value)}
              pattern="[A-Za-z]{2}"
              maxLength={2}
              required
            />
          </label>
          <label className="field">
            <span>Language</span>
            <input
              value={settings.language}
              onChange={(event) => update("language", event.target.value)}
              pattern="[A-Za-z]{2}"
              maxLength={2}
              required
            />
          </label>
          <label className="field">
            <span>Date posted</span>
            <select
              value={settings.datePosted}
              onChange={(event) => update("datePosted", event.target.value)}
            >
              <option value="today">Today</option>
              <option value="3days">Past 3 days</option>
              <option value="week">Past week</option>
              <option value="month">Past month</option>
            </select>
          </label>
          <label className="field">
            <span>Maximum jobs</span>
            <select
              value={settings.maxResults}
              onChange={(event) => update("maxResults", Number(event.target.value))}
            >
              {[5, 10, 20, 30, 50, 75, 100].map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
            <small>
              Up to {Math.ceil(settings.maxResults / 5)} RapidAPI requests
            </small>
          </label>
        </div>

        <div className="settings-row settings-row-textareas">
          <label className="field">
            <span>Allowed cities</span>
            <small>One exact city per line</small>
            <textarea
              value={settings.cities}
              onChange={(event) => update("cities", event.target.value)}
              rows={4}
              required
            />
          </label>
          <label className="field">
            <span>Allowed role phrases</span>
            <small>One title phrase per line</small>
            <textarea
              value={settings.roles}
              onChange={(event) => update("roles", event.target.value)}
              rows={7}
              required
            />
          </label>
        </div>

        <div className="settings-footer">
          <span>Settings are saved in this browser.</span>
          <button className="text-button" type="button" onClick={onReset}>
            Reset defaults
          </button>
        </div>
      </div>
    </details>
  );
}

export default function App() {
  const [settings, setSettings] = useState(readStoredSettings);
  const [currentJobs, setCurrentJobs] = useState([]);
  const [history, setHistory] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState("");
  const [lastCheckedAt, setLastCheckedAt] = useState(null);

  useEffect(() => {
    localStorage.setItem("job-scout-settings-v2", JSON.stringify(settings));
  }, [settings]);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await request("/jobs/history"));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const previousJobs = useMemo(() => {
    const currentIds = new Set(currentJobs.map((job) => job.job_id));
    return history.filter((job) => !currentIds.has(job.job_id));
  }, [currentJobs, history]);

  const fetchJobs = useCallback(
    async ({ throwOnError = false, searchSettings = settings } = {}) => {
      setFetching(true);
      setError("");

      try {
        const jobs = await request(buildFetchPath(searchSettings));
        setCurrentJobs(jobs);
        setLastCheckedAt(new Date());
        await loadHistory();
        return jobs;
      } catch (requestError) {
        setError(requestError.message);
        if (throwOnError) throw requestError;
        return [];
      } finally {
        setFetching(false);
      }
    },
    [loadHistory, settings],
  );

  useEffect(() => {
    const modelContext = document.modelContext;
    if (!modelContext?.registerTool) return undefined;

    const lifecycle = new AbortController();
    const register = modelContext.registerTool(
      {
        name: "fetch_new_jobs",
        title: "Fetch new jobs",
        description:
          "Make one on-demand JSearch request with configurable search filters and update the visible job lists.",
        inputSchema: {
          type: "object",
          properties: {
            query: { type: "string", minLength: 2, maxLength: 200 },
            country: { type: "string", pattern: "^[A-Za-z]{2}$" },
            language: { type: "string", pattern: "^[A-Za-z]{2}$" },
            datePosted: {
              type: "string",
              enum: ["today", "3days", "week", "month"],
            },
            maxResults: { type: "integer", minimum: 1, maximum: 100 },
            cities: { type: "array", items: { type: "string" }, minItems: 1 },
            roles: { type: "array", items: { type: "string" }, minItems: 1 },
          },
          additionalProperties: false,
        },
        annotations: {
          readOnlyHint: false,
          untrustedContentHint: true,
        },
        async execute(input = {}) {
          const nextSettings = {
            ...settings,
            ...input,
            cities: input.cities?.join("\n") ?? settings.cities,
            roles: input.roles?.join("\n") ?? settings.roles,
          };
          setSettings(nextSettings);
          const jobs = await fetchJobs({
            throwOnError: true,
            searchSettings: nextSettings,
          });
          return { newJobCount: jobs.length, jobs };
        },
      },
      { signal: lifecycle.signal },
    );

    void Promise.resolve(register).catch(() => lifecycle.abort());
    return () => lifecycle.abort();
  }, [fetchJobs, settings]);

  const cityLabel = splitLines(settings.cities).slice(0, 2).join(" · ");

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Job Scout home">
          <span className="brand-mark" aria-hidden="true">J</span>
          <span>Job Scout</span>
        </a>
        <span className="location-pill">{cityLabel || "Custom search"}</span>
      </header>

      <section className="dashboard" id="top">
        <div className="intro">
          <p className="eyebrow">PERSONAL JOB ALERTS</p>
          <h1>Good roles, without the noise.</h1>
          <p className="subtitle">
            Fresh software roles matched to your filters. Nothing runs until
            you ask.
          </p>

          <div className="actions">
            <button
              type="button"
              onClick={() => fetchJobs()}
              disabled={fetching}
            >
              {fetching ? "Checking JSearch…" : "Fetch new jobs"}
            </button>
            <p className="last-checked" aria-live="polite">
              {lastCheckedAt
                ? `Last checked ${lastCheckedAt.toLocaleTimeString("en-IN", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}`
                : `Up to ${Math.ceil(settings.maxResults / 5)} API requests per click`}
            </p>
          </div>
        </div>

        <aside className="summary" aria-label="Job summary">
          <div>
            <strong>{currentJobs.length}</strong>
            <span>New this check</span>
          </div>
          <div>
            <strong>{history.length}</strong>
            <span>Retained 30 days</span>
          </div>
        </aside>
      </section>

      <SearchSettings
        settings={settings}
        onChange={setSettings}
        onReset={() => setSettings({ ...DEFAULT_SETTINGS })}
      />

      {error && (
        <div className="error-banner" role="alert">
          <strong>Couldn’t fetch jobs.</strong>
          <span>{error}</span>
        </div>
      )}

      <section className="jobs-section" aria-labelledby="current-heading">
        <div className="section-heading">
          <div>
            <p className="section-kicker">LATEST CHECK</p>
            <h2 id="current-heading">New matches</h2>
          </div>
          <div className="section-tools">
            <button
              className="export-button"
              type="button"
              onClick={() => downloadJson(currentJobs, "latest-job-matches")}
              disabled={!currentJobs.length}
            >
              Export JSON
            </button>
            <span className="count">{currentJobs.length}</span>
          </div>
        </div>

        <div className="job-list" tabIndex="0">
          {currentJobs.length ? (
            currentJobs.map((job) => <JobCard key={job.job_id} job={job} />)
          ) : (
            <EmptyState>
              {lastCheckedAt
                ? "No unseen matches passed every filter this time."
                : "Fetch jobs to see your newest matches here."}
            </EmptyState>
          )}
        </div>
      </section>

      <section className="jobs-section history-section" aria-labelledby="history-heading">
        <div className="section-heading">
          <div>
            <p className="section-kicker">ARCHIVE</p>
            <h2 id="history-heading">Previously fetched</h2>
          </div>
          <div className="section-tools">
            <button
              className="export-button"
              type="button"
              onClick={() => downloadJson(previousJobs, "previously-fetched-jobs")}
              disabled={!previousJobs.length}
            >
              Export JSON
            </button>
            <span className="count">{previousJobs.length}</span>
          </div>
        </div>

        <div className="job-list" tabIndex="0">
          {loadingHistory ? (
            <EmptyState>Loading your job history…</EmptyState>
          ) : previousJobs.length ? (
            previousJobs.map((job) => <JobCard key={job.job_id} job={job} />)
          ) : (
            <EmptyState>Your fetched-job history will appear here.</EmptyState>
          )}
        </div>
      </section>

      <footer>
        On-demand cursor pagination · 100-job cap · 30-day retention
      </footer>
    </main>
  );
}
