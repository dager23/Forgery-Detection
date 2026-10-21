import { FileSearch } from "lucide-react";
import { Link } from "react-router";
import { EmptyState } from "../components/ui";

export default function NotFound({ inApp }: { inApp?: boolean }) {
  return (
    <div className={inApp ? "" : "flex min-h-dvh items-center justify-center"}>
      <EmptyState icon={<FileSearch className="size-6" />} title="Page not found">
        <p>The page you were looking for doesn't exist or was moved.</p>
        <Link to={inApp ? "/app" : "/"} className="mt-4 inline-block font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400">
          {inApp ? "Back to dashboard" : "Back to home"}
        </Link>
      </EmptyState>
    </div>
  );
}
