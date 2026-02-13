import { Link } from 'react-router-dom';

interface HelpLinkProps {
  sectionId: string;
  label?: string;
}

function HelpLink({ sectionId, label = 'Open help section' }: HelpLinkProps) {
  return (
    <Link
      to={`/help#${sectionId}`}
      aria-label={label}
      title={label}
      className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-gray-500 text-xs text-gray-300 hover:border-blue-400 hover:text-blue-300"
    >
      ?
    </Link>
  );
}

export default HelpLink;
