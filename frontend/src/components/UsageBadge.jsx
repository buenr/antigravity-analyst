import React from 'react';
import { Coins } from 'lucide-react';

function compactNumber(n) {
  if (n == null) return '–';
  if (n < 1000) return `${n}`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return `${(n / 1_000_000).toFixed(2).replace(/\.00$/, '')}M`;
}

/**
 * Rough cost estimate using mid-range pricing from the Antigravity docs.
 * Input ~$1/M tokens (with 50–70% cached, so we weight 0.4); output ~$3/M.
 * This is an estimate only — actual invoice is authoritative.
 */
function estimateCostUsd(usage) {
  if (!usage) return null;
  const input = usage.total_input_tokens || 0;
  const cached = usage.total_cached_tokens || 0;
  const output = usage.total_output_tokens || 0;
  const billedInput = Math.max(input - cached, 0);
  const usd = (billedInput * 1.0e-6) * 0.5 + (cached * 1.0e-6) * 0.1 + (output * 3.0e-6);
  if (!Number.isFinite(usd) || usd <= 0) return null;
  return usd;
}

export default function UsageBadge({ usage }) {
  if (!usage) return null;

  const input = usage.total_input_tokens;
  const output = usage.total_output_tokens;
  const cached = usage.total_cached_tokens;
  const thought = usage.total_thought_tokens;
  const total = usage.total_tokens;
  const cost = estimateCostUsd(usage);

  const parts = [];
  if (input != null) parts.push(`${compactNumber(input)} in`);
  if (output != null) parts.push(`${compactNumber(output)} out`);
  if (cached) parts.push(`${compactNumber(cached)} cached`);
  if (thought) parts.push(`${compactNumber(thought)} thought`);

  return (
    <div
      className="mt-2 inline-flex items-center gap-1.5 text-xs text-gray-500 bg-gray-50 border border-gray-200 rounded-full px-2.5 py-1"
      title={
        `total ${total ?? '–'} tokens` +
        (cost ? ` · est ~$${cost.toFixed(cost < 0.1 ? 4 : 2)}` : '')
      }
    >
      <Coins className="w-3 h-3 text-gray-400" />
      <span>{parts.join(' · ') || '–'}</span>
      {cost != null && (
        <span className="text-gray-400">
          · ~${cost.toFixed(cost < 0.1 ? 4 : 2)}
        </span>
      )}
    </div>
  );
}
