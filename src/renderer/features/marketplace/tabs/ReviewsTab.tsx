/**
 * ReviewsTab — existing review list plus a submit-review form (rating +
 * comment). Submitting requires authentication (the server derives
 * `reviewer` from the signed-in user — no client-supplied name).
 * Data: GET /marketplace/listings/{id}/reviews, POST /marketplace/reviews
 */
import { useState, useEffect } from "react";
import { apiFetch, parseJSON } from "../../../shared/utils/api";
import { useToast } from "../../../contexts/ToastContext";

interface Review {
  id: string;
  listing_id: string;
  rating: number;
  comment: string | null;
  reviewer: string;
  created_at: number;
}

export function ReviewsTab({ listingId }: { listingId: string }) {
  const toast = useToast();
  const [reviews, setReviews] = useState<Review[] | null>(null);
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    try {
      const r = await apiFetch(`/marketplace/listings/${listingId}/reviews`);
      if (!r.ok) throw new Error();
      const d = await parseJSON<Review[]>(r, "reviews");
      setReviews(d);
    } catch {
      setReviews([]);
    }
  };

  useEffect(() => { setReviews(null); void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [listingId]);

  const submit = async () => {
    setSubmitting(true);
    try {
      const r = await apiFetch(`/marketplace/reviews`, {
        method: "POST",
        body: JSON.stringify({ listing_id: listingId, rating, comment: comment || null }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        if (r.status === 401) throw new Error("Sign in to leave a review");
        throw new Error(body?.detail ?? "Review submission failed");
      }
      setComment("");
      toast("Review submitted", "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Review submission failed", "err");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", border: "1px solid var(--border)", borderRadius: 10, padding: 10 }}>
        <select
          value={rating}
          onChange={e => setRating(Number(e.target.value))}
          style={{
            background: "var(--bg-base)", border: "1px solid var(--border)", borderRadius: 6,
            color: "var(--t1)", fontSize: 12, padding: "4px 6px",
          }}
        >
          {[5, 4, 3, 2, 1].map(n => <option key={n} value={n}>{"★".repeat(n)}</option>)}
        </select>
        <input
          value={comment}
          onChange={e => setComment(e.target.value)}
          placeholder="Leave a review…"
          style={{
            flex: 1, background: "var(--bg-base)", border: "1px solid var(--border)", borderRadius: 6,
            color: "var(--t1)", fontSize: 12, padding: "6px 10px", fontFamily: "inherit", outline: "none",
          }}
        />
        <button
          onClick={() => void submit()}
          disabled={submitting}
          style={{
            padding: "6px 14px", borderRadius: 6, border: "none", cursor: submitting ? "wait" : "pointer",
            background: "linear-gradient(135deg,#FFD700,#D4AF37)", color: "#0a0a0a", fontSize: 12, fontWeight: 700,
          }}
        >
          {submitting ? "…" : "Submit"}
        </button>
      </div>

      {reviews === null ? (
        <div style={{ fontSize: 12, color: "var(--t4)" }}>Loading reviews…</div>
      ) : reviews.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--t4)" }}>No reviews yet — be the first.</div>
      ) : (
        reviews.map(rv => (
          <div key={rv.id} style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 12, color: "#FFB300" }}>
                {"★".repeat(Math.round(rv.rating))}{"☆".repeat(5 - Math.round(rv.rating))}
              </span>
              <span style={{ fontSize: 11, color: "var(--t4)" }}>{rv.reviewer}</span>
            </div>
            {rv.comment && <p style={{ fontSize: 12, color: "var(--t3)", margin: "4px 0 0" }}>{rv.comment}</p>}
          </div>
        ))
      )}
    </div>
  );
}
