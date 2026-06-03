import React, { useMemo, useState } from 'react';
import {
  Terminal,
  Code,
  Search,
  Globe,
  Brain,
  ChevronDown,
  ChevronRight,
  Loader2,
} from 'lucide-react';

const TOOL_ICON = {
  code_execution: Code,
  terminal: Terminal,
  tool_call: Search,
  thought: Brain,
};

function StepBlock({ step }) {
  const [open, setOpen] = useState(step.kind !== 'thought');
  const Icon = TOOL_ICON[step.kind] || Globe;

  const headerLabel = {
    code_execution: 'Code execution',
    terminal: 'Terminal output',
    tool_call: 'Tool call',
    thought: 'Thinking',
  }[step.kind] || step.kind;

  const preview = step.lines[step.lines.length - 1] || '';

  return (
    <div className="border border-gray-800 rounded-lg bg-gray-950 text-gray-100 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center w-full gap-2 px-3 py-2 text-left hover:bg-gray-900"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-gray-400 shrink-0" />
        )}
        <Icon className="w-3.5 h-3.5 text-primary-400 shrink-0" />
        <span className="text-xs font-medium text-gray-300 shrink-0">{headerLabel}</span>
        {!open && (
          <span className="text-xs text-gray-500 truncate font-mono">
            {preview.slice(0, 80)}
          </span>
        )}
      </button>
      {open && (
        <pre className="px-3 pb-3 pt-1 text-xs font-mono whitespace-pre-wrap text-green-300 leading-relaxed max-h-64 overflow-y-auto">
          {step.lines.join('\n') || '...'}
        </pre>
      )}
    </div>
  );
}

/**
 * Buckets the raw SSE events into a list of step blocks for display.
 * Adjacent events of the same kind collapse into a single block.
 */
function bucketEvents(events) {
  const blocks = [];
  let current = null;

  for (const ev of events) {
    const kind = ev.event_type;
    if (!['code_execution', 'terminal', 'tool_call', 'thought'].includes(kind)) {
      continue;
    }
    const message = ev.message || '';
    if (current && current.kind === kind) {
      current.lines.push(message);
    } else {
      current = { kind, lines: [message] };
      blocks.push(current);
    }
  }
  return blocks;
}

export default function AgentActivity({ events, isStreaming }) {
  const blocks = useMemo(() => bucketEvents(events), [events]);

  if (!isStreaming && blocks.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      {isStreaming && blocks.length === 0 && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
          <span>Initializing sandbox...</span>
        </div>
      )}
      {blocks.map((block, idx) => (
        <StepBlock key={idx} step={block} />
      ))}
      {isStreaming && blocks.length > 0 && (
        <div className="flex items-center gap-2 text-xs text-gray-500 pl-1">
          <Loader2 className="w-3 h-3 animate-spin" />
          <span>Working...</span>
        </div>
      )}
    </div>
  );
}
