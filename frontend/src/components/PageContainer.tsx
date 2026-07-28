import { ReactNode } from "react";

type PageContainerProps = {
  title: string;
  description?: string;
  children?: ReactNode;
};

export function PageContainer({
  title,
  description,
  children,
}: PageContainerProps) {
  return (
    <section className="page-container">
      <header className="page-header">
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </header>
      <div>{children}</div>
    </section>
  );
}
