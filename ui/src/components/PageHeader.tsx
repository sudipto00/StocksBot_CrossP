import { ReactNode } from 'react';
import HelpLink from './HelpLink';

interface PageHeaderProps {
  title: string;
  description: string;
  helpSection?: string;
  actions?: ReactNode;
}

function PageHeader({ title, description, helpSection, actions }: PageHeaderProps) {
  return (
    <div className="mb-6 flex items-center justify-between gap-4">
      <div>
        <div className="flex items-center gap-2">
          <h2 className="text-3xl font-bold text-white">{title}</h2>
          {helpSection && <HelpLink sectionId={helpSection} label={`${title} help`} />}
        </div>
        <p className="text-gray-400 mt-1">{description}</p>
      </div>
      {actions}
    </div>
  );
}

export default PageHeader;
