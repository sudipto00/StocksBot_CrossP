import { Link } from 'react-router-dom';

const steps = [
  { label: '1. Configure', to: '/settings' },
  { label: '2. Select Universe', to: '/screener' },
  { label: '3. Activate Strategy', to: '/strategy' },
  { label: '4. Monitor', to: '/dashboard' },
];

function GuidedFlowStrip() {
  return (
    <div className="mb-6 rounded-lg border border-blue-800 bg-blue-950/30 p-3">
      <div className="text-xs uppercase tracking-wide text-blue-300 mb-2">Guided Trading Flow</div>
      <div className="flex flex-wrap gap-2">
        {steps.map((step) => (
          <Link key={step.label} to={step.to} className="rounded bg-blue-900/50 px-3 py-1 text-xs text-blue-100 hover:bg-blue-800/70">
            {step.label}
          </Link>
        ))}
      </div>
    </div>
  );
}

export default GuidedFlowStrip;
