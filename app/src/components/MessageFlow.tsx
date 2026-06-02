import { useState, useCallback, useMemo } from 'react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { Message } from '@/types';
import { User, Cpu, Wrench, AlertTriangle, Terminal, Copy, Check, ChevronDown, ChevronUp } from 'lucide-react';

interface Props {
  messages: Message[];
}

function RoleIcon({ role }: { role: string }) {
  switch (role) {
    case 'user': return <User className="w-4 h-4 text-blue-400" />;
    case 'assistant': return <Cpu className="w-4 h-4 text-emerald-400" />;
    case 'tool': return <Wrench className="w-4 h-4 text-amber-400" />;
    case 'system': return <Terminal className="w-4 h-4 text-purple-400" />;
    default: return <AlertTriangle className="w-4 h-4 text-slate-400" />;
  }
}

function RoleBadge({ role }: { role: string }) {
  const variants: Record<string, string> = {
    user: 'bg-blue-900/40 text-blue-300 border-blue-700',
    assistant: 'bg-emerald-900/40 text-emerald-300 border-emerald-700',
    tool: 'bg-amber-900/40 text-amber-300 border-amber-700',
    system: 'bg-purple-900/40 text-purple-300 border-purple-700',
  };
  return (
    <Badge variant="outline" className={cn('text-[10px] px-1.5 py-0 font-medium', variants[role] || '')}>
      <span className="capitalize">{role}</span>
    </Badge>
  );
}

interface CodeBlock {
  type: 'code';
  lang: string;
  code: string;
}

interface TextBlock {
  type: 'text';
  text: string;
}

type Block = CodeBlock | TextBlock;

function parseContent(content: string): Block[] {
  const blocks: Block[] = [];
  const regex = /```(\w*)\n([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      blocks.push({ type: 'text', text: content.slice(lastIndex, match.index) });
    }
    blocks.push({ type: 'code', lang: match[1] || 'text', code: match[2] });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < content.length) {
    blocks.push({ type: 'text', text: content.slice(lastIndex) });
  }

  if (blocks.length === 0) {
    blocks.push({ type: 'text', text: content });
  }

  return blocks;
}

const FOLD_THRESHOLD = 500;

function CodeBlockView({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  }, [code]);

  return (
    <div className="mt-1.5 rounded-lg overflow-hidden border border-slate-700/60 bg-slate-900/60">
      <div className="flex items-center justify-between px-2.5 py-1 bg-slate-800/60 border-b border-slate-700/40">
        <span className="text-[10px] text-slate-500 font-mono uppercase">{lang || 'code'}</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-5 px-1.5 text-[10px] text-slate-500 hover:text-slate-300"
          onClick={handleCopy}
        >
          {copied ? <Check className="w-3 h-3 mr-0.5" /> : <Copy className="w-3 h-3 mr-0.5" />}
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <pre className="p-2.5 text-xs font-mono text-slate-300 whitespace-pre-wrap break-words overflow-x-auto max-h-64 overflow-y-auto">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function TextBlockView({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const shouldFold = text.length > FOLD_THRESHOLD;

  const displayText = shouldFold && !expanded
    ? text.slice(0, FOLD_THRESHOLD) + '...'
    : text;

  return (
    <div>
      <div className="text-sm text-slate-300 whitespace-pre-wrap break-words leading-relaxed">
        {displayText}
      </div>
      {shouldFold && (
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-1 text-[10px] text-slate-500 hover:text-slate-300 mt-1"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? <ChevronUp className="w-3 h-3 mr-0.5" /> : <ChevronDown className="w-3 h-3 mr-0.5" />}
          {expanded ? 'Show less' : `Show more (${text.length - FOLD_THRESHOLD} chars)`}
        </Button>
      )}
    </div>
  );
}

function MessageContent({ content }: { content: string }) {
  const blocks = useMemo(() => parseContent(content), [content]);

  return (
    <div className="space-y-1">
      {blocks.map((block, idx) => {
        if (block.type === 'code') {
          return <CodeBlockView key={idx} lang={block.lang} code={block.code} />;
        }
        return <TextBlockView key={idx} text={block.text} />;
      })}
    </div>
  );
}

function messageKey(msg: Message, index: number): string {
  // Use content hash + role for stable key
  const hash = msg.content
    ? msg.content.slice(0, 50) + msg.content.length
    : msg.tool_calls?.map(tc => tc.id).join('') || '';
  return `${msg.role}_${index}_${hash}`;
}

export default function MessageFlow({ messages }: Props) {
  const endRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  if (messages.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        No messages yet
      </div>
    );
  }

  return (
    <ScrollArea className="h-full">
      <div className="space-y-1.5 p-3">
        {messages.map((msg, i) => (
          <div
            key={messageKey(msg, i)}
            className={cn(
              "flex gap-2.5 p-2.5 rounded-lg transition-colors",
              msg.role === 'system' && 'bg-purple-900/15',
              msg.role === 'user' && 'bg-blue-900/10',
              msg.role === 'assistant' && 'bg-emerald-900/10',
              msg.role === 'tool' && 'bg-amber-900/10',
            )}
          >
            <div className="mt-0.5 shrink-0">
              <RoleIcon role={msg.role} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 mb-1">
                <RoleBadge role={msg.role} />
                {msg.name && (
                  <span className="text-xs text-slate-500 truncate">{msg.name}</span>
                )}
              </div>
              {msg.content && <MessageContent content={msg.content} />}
              {msg.tool_calls && msg.tool_calls.length > 0 && (
                <div className="mt-1.5 space-y-1">
                  {msg.tool_calls.map((tc) => (
                    <div key={tc.id} className="bg-slate-800/60 rounded px-2 py-1.5 text-xs font-mono border border-slate-700/50 overflow-x-auto">
                      <span className="text-cyan-400">{tc.function.name}</span>
                      <span className="text-slate-600 mx-1">(</span>
                      <span className="text-slate-300">{tc.function.arguments}</span>
                      <span className="text-slate-600">)</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </ScrollArea>
  );
}
