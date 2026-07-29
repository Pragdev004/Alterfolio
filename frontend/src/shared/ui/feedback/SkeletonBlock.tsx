type SkeletonBlockProps = {
  className?: string;
};

export function SkeletonBlock({ className = "" }: SkeletonBlockProps) {
  return <div className={`skeleton-block ${className}`.trim()} aria-hidden="true" />;
}
