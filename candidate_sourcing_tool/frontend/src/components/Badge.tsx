import React from 'react';

interface BadgeProps {
  children: React.ReactNode;
  variant?: 'emerald' | 'blue' | 'amber' | 'rose' | 'slate' | 'indigo' | 'purple';
  size?: 'sm' | 'md';
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'slate',
  size = 'sm',
}) => {
  const variantStyles = {
    emerald: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    blue: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
    amber: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    rose: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
    slate: 'bg-slate-800 text-slate-300 border-slate-700',
    indigo: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
    purple: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  };

  const sizeStyles = {
    sm: 'text-[11px] px-2 py-0.5',
    md: 'text-xs px-2.5 py-1',
  };

  return (
    <span
      className={`inline-flex items-center gap-1 font-medium rounded-md border ${variantStyles[variant]} ${sizeStyles[size]}`}
    >
      {children}
    </span>
  );
};

export const ScoreBadge: React.FC<{ score: number; percentage?: number }> = ({ score, percentage }) => {
  const pct = percentage ?? Math.round(score);
  let variant: 'emerald' | 'blue' | 'amber' | 'rose' = 'rose';
  let label = 'Low Match';

  if (pct >= 80) {
    variant = 'emerald';
    label = 'Strong Match';
  } else if (pct >= 60) {
    variant = 'blue';
    label = 'Good Match';
  } else if (pct >= 40) {
    variant = 'amber';
    label = 'Potential';
  }

  return (
    <Badge variant={variant} size="md">
      <span className="font-bold">{pct}%</span>
      <span className="opacity-80">· {label}</span>
    </Badge>
  );
};
