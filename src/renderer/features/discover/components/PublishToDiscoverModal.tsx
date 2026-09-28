import { useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useOrg } from "../../../contexts/OrgContext";
import type { CreationType, FlowCreation } from "../types/creation.types";
import { createCreation, fetchMyCreations, publishCreation } from "../services/discoverService";

interface PublishToDiscoverModalProps {
  sourceType: Extract<CreationType, "APP" | "AGENT">;
  sourceId: string;
  defaultTitle: string;
  defaultDescription?: string;
  onClose: () => void;
  onSuccess: (creation: FlowCreation) => void;
}

export function PublishToDiscoverModal({
  sourceType,
  sourceId,
  defaultTitle,
  defaultDescription = "",
  onClose,
  onSuccess,
}: PublishToDiscoverModalProps) {
  const { t } = useTranslation("discover");
  const { currentOrgId } = useOrg();

  const [title, setTitle]             = useState(defaultTitle);
  const [description, setDescription] = useState(defaultDescription);
  const [tagsInput, setTagsInput]     = useState("");
  const [submitting, setSubmitting]           = useState(false);
  const [checkingDup, setCheckingDup]         = useState(false);
  const [error, setError]                     = useState<string | null>(null);
  const [dupWarning, setDupWarning]           = useState<string | null>(null);
  const [publishImmediately, setPublishImmediately] = useState(false);
  const [publishingAfterCreate, setPublishingAfterCreate] = useState(false);
  const [createSucceeded, setCreateSucceeded] = useState(false);

  // Frontend duplicate check — UX enhancement only, not a security gate.
  useEffect(() => {
    if (!currentOrgId || !sourceId) return;
    let cancelled = false;
    setCheckingDup(true);
    fetchMyCreations(currentOrgId, { limit: 100 })
      .then(resp => {
        if (cancelled) return;
        const dup = resp.items.find(
          c => c.source_type === sourceType && c.source_id === sourceId
        );
        if (dup) setDupWarning(t("publish.modal.duplicateWarning"));
      })
      .catch(() => { /* ignore — duplicate check is best-effort */ })
      .finally(() => { if (!cancelled) setCheckingDup(false); });
    return () => { cancelled = true; };
  }, [currentOrgId, sourceId, sourceType, t]);

  const handleSubmit = useCallback(async () => {
    if (!title.trim() || !currentOrgId || submitting || !!dupWarning) return;
    setSubmitting(true);
    setError(null);

    const tags = tagsInput
      .split(",")
      .map(tag => tag.trim())
      .filter(Boolean);

    try {
      const creation = await createCreation(currentOrgId, {
        type: sourceType,
        title: title.trim(),
        description: description.trim() || undefined,
        visibility: "private",
        source_type: sourceType,
        source_id: sourceId,
        tags,
      });

      if (!publishImmediately) {
        onSuccess(creation);
        return;
      }

      setPublishingAfterCreate(true);
      try {
        const published = await publishCreation(creation.id, currentOrgId);
        onSuccess(published);
      } catch (pubErr) {
        setCreateSucceeded(true);
        setError(pubErr instanceof Error ? pubErr.message : t("publish.modal.publishFailed"));
      } finally {
        setPublishingAfterCreate(false);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t("publish.modal.error"));
    } finally {
      setSubmitting(false);
    }
  }, [
    title, description, tagsInput, currentOrgId,
    sourceType, sourceId, submitting, dupWarning,
    publishImmediately, t, onSuccess,
  ]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("publish.modal.title")}
      style={{
        position: "fixed", inset: 0, zIndex: 600,
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: "16px",
      }}
      onKeyDown={onKey}
    >
      {/* Backdrop */}
      <div
        style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.5)" }}
        onClick={onClose}
        role="button"
        tabIndex={-1}
        aria-label={t("publish.modal.close")}
      />

      {/* Panel */}
      <div style={{
        position: "relative", zIndex: 1,
        background: "var(--bg-surface)",
        borderRadius: 16,
        border: "1px solid var(--b1)",
        boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
        width: "100%", maxWidth: 480,
        padding: "28px 28px 24px",
        display: "flex", flexDirection: "column", gap: 18,
      }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--t1)", margin: 0 }}>
              {t("publish.modal.title")}
            </h2>
            <p style={{ fontSize: 12, color: "var(--t4)", margin: "4px 0 0", lineHeight: 1.4 }}>
              {t("publish.modal.subtitle")}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t("publish.modal.close")}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: "var(--t4)", padding: 4, flexShrink: 0,
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        {/* Source type badge */}
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          padding: "4px 10px", borderRadius: 99, width: "fit-content",
          background: "var(--accent)18", border: "1px solid var(--accent)44",
          fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
          textTransform: "uppercase", color: "var(--accent)",
        }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            {sourceType === "APP"
              ? <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>
              : <><path d="M12 2a5 5 0 0 1 5 5v2a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5z"/><path d="M2 20c0-3 3.5-5 10-5s10 2 10 5"/></>
            }
          </svg>
          {sourceType}
        </div>

        {/* Duplicate warning */}
        {!checkingDup && dupWarning && (
          <div style={{
            padding: "10px 14px", borderRadius: 8,
            background: "#f59e0b18", border: "1px solid #f59e0b44",
            fontSize: 12, color: "#d97706",
          }}>
            ⚠ {dupWarning}
          </div>
        )}

        {/* Title */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)" }}>
            {t("publish.modal.titleLabel")} *
          </label>
          <input
            value={title}
            onChange={e => setTitle(e.target.value)}
            maxLength={200}
            style={{
              padding: "9px 12px", borderRadius: 8,
              border: "1px solid var(--b2)",
              background: "var(--bg-input)",
              color: "var(--t1)", fontSize: 13,
              outline: "none", width: "100%", boxSizing: "border-box",
            }}
            onFocus={e => { e.currentTarget.style.borderColor = "var(--accent)"; }}
            onBlur={e => { e.currentTarget.style.borderColor = "var(--b2)"; }}
          />
        </div>

        {/* Description */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)" }}>
            {t("publish.modal.descriptionLabel")}
          </label>
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            rows={3}
            style={{
              padding: "9px 12px", borderRadius: 8,
              border: "1px solid var(--b2)",
              background: "var(--bg-input)",
              color: "var(--t1)", fontSize: 13,
              outline: "none", width: "100%", boxSizing: "border-box",
              resize: "vertical", lineHeight: 1.5, fontFamily: "inherit",
            }}
            onFocus={e => { e.currentTarget.style.borderColor = "var(--accent)"; }}
            onBlur={e => { e.currentTarget.style.borderColor = "var(--b2)"; }}
          />
        </div>

        {/* Tags */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "var(--t3)" }}>
            {t("publish.modal.tagsLabel")}
          </label>
          <input
            value={tagsInput}
            onChange={e => setTagsInput(e.target.value)}
            placeholder={t("publish.modal.tagsPlaceholder")}
            style={{
              padding: "9px 12px", borderRadius: 8,
              border: "1px solid var(--b2)",
              background: "var(--bg-input)",
              color: "var(--t1)", fontSize: 13,
              outline: "none", width: "100%", boxSizing: "border-box",
            }}
            onFocus={e => { e.currentTarget.style.borderColor = "var(--accent)"; }}
            onBlur={e => { e.currentTarget.style.borderColor = "var(--b2)"; }}
          />
          <span style={{ fontSize: 11, color: "var(--t5)" }}>
            {t("publish.modal.tagsHint")}
          </span>
        </div>

        {/* Publish immediately checkbox */}
        <label style={{
          display: "flex", alignItems: "flex-start", gap: 10,
          cursor: submitting ? "not-allowed" : "pointer",
          userSelect: "none",
        }}>
          <input
            type="checkbox"
            checked={publishImmediately}
            onChange={e => setPublishImmediately(e.target.checked)}
            disabled={submitting}
            style={{ marginTop: 2, accentColor: "var(--accent)", flexShrink: 0, cursor: "inherit" }}
          />
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--t2)" }}>
              {t("publish.modal.publishNowLabel")}
            </div>
            <div style={{ fontSize: 11, color: "var(--t5)", marginTop: 2 }}>
              {t("publish.modal.publishNowHint")}
            </div>
          </div>
        </label>

        {/* Visibility notice */}
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 12px", borderRadius: 8,
          background: publishImmediately ? "var(--accent)18" : "var(--b1)",
          border: publishImmediately ? "1px solid var(--accent)33" : "none",
          fontSize: 12,
          color: publishImmediately ? "var(--accent)" : "var(--t4)",
        }}>
          {publishImmediately ? (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
          )}
          {publishImmediately ? t("publish.modal.publicNotice") : t("publish.modal.privateNotice")}
        </div>

        {/* Error */}
        {error && (
          <div style={{
            padding: "10px 14px", borderRadius: 8,
            background: "var(--red, #ef4444)18", border: "1px solid var(--red, #ef4444)44",
            fontSize: 12, color: "var(--red, #ef4444)",
          }}>
            {error}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button
            onClick={onClose}
            disabled={submitting}
            style={{
              padding: "9px 18px", borderRadius: 8,
              border: "1px solid var(--b2)", background: "none",
              color: "var(--t3)", fontSize: 13, fontWeight: 600,
              cursor: submitting ? "not-allowed" : "pointer",
              opacity: submitting ? 0.6 : 1,
            }}
          >
            {t("publish.modal.cancel")}
          </button>
          <button
            onClick={() => void handleSubmit()}
            disabled={submitting || checkingDup || !title.trim() || !currentOrgId || !!dupWarning || createSucceeded}
            style={{
              padding: "9px 18px", borderRadius: 8,
              border: "none",
              background: submitting || checkingDup || !title.trim() || !currentOrgId || !!dupWarning || createSucceeded
                ? "var(--b2)" : "var(--accent)",
              color: submitting || checkingDup || !title.trim() || !currentOrgId || !!dupWarning || createSucceeded
                ? "var(--t4)" : "#fff",
              fontSize: 13, fontWeight: 600,
              cursor: submitting || checkingDup || !title.trim() || !currentOrgId || !!dupWarning || createSucceeded
                ? "not-allowed" : "pointer",
              transition: "all 0.15s",
            }}
          >
            {publishingAfterCreate
              ? t("publish.modal.publishing")
              : submitting
              ? t("publish.modal.submitting")
              : publishImmediately
              ? t("publish.modal.submitPublish")
              : t("publish.modal.submit")}
          </button>
        </div>
      </div>
    </div>
  );
}
