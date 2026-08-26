/**
 * The connection's health, in the shape every driver reports it.
 *
 * `get_info` carries `connection_status`: ordered keys, each with its answer
 * or `"pending"` until that check has answered, and a value beginning
 * `failed` when it failed. The driver decides what the checks are and what
 * they say; the page shows one row per key and judges nothing beyond these
 * two words.
 */

export const PENDING = "pending";

export const isFailed = (value) => /^failed\b/i.test(String(value));
