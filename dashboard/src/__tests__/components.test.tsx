import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within, cleanup } from '@testing-library/react';
import '@testing-library/jest-dom';

vi.mock('../components/RiskScoreCard.css', () => ({}));
vi.mock('../components/IncidentTimeline.css', () => ({}));
vi.mock('../components/SLOBurnChart.css', () => ({}));

let mockToggleTheme = vi.fn();
let mockSetTheme = vi.fn();
let mockTheme: 'light' | 'dark' = 'light';

vi.mock('../context/ThemeContext', () => ({
  useTheme: () => ({
    theme: mockTheme,
    toggleTheme: mockToggleTheme,
    setTheme: mockSetTheme,
  }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  const React = await import('react');
  return {
    ...actual,
    BrowserRouter: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
    NavLink: ({ to, children, className, onClick, ...rest }: any) =>
      React.createElement('a', { href: to, className: typeof className === 'function' ? className({ isActive: to === '/' }) : className, onClick, ...rest }, children),
    useLocation: () => ({ pathname: '/', search: '', hash: '', state: null, key: 'default' }),
  };
});

vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(() => ({ data: undefined, isLoading: false, error: null })),
  useMutation: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useQueryClient: vi.fn(() => ({ invalidateQueries: vi.fn() })),
  QueryClient: vi.fn(() => ({})),
  QueryClientProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  LineChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
}));

describe('ThemeToggle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTheme = 'light';
  });

  it('renders a button', async () => {
    const { default: ThemeToggle } = await import('../components/ThemeToggle');
    render(<ThemeToggle />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('shows moon icon (switch to dark) in light mode', async () => {
    mockTheme = 'light';
    const { default: ThemeToggle } = await import('../components/ThemeToggle');
    render(<ThemeToggle />);
    const btn = screen.getByRole('button');
    expect(btn).toHaveAttribute('aria-label', 'Switch to dark mode');
    expect(btn).toHaveAttribute('aria-pressed', 'false');
    expect(btn.querySelector('path[d*="11.21 3"]')).toBeInTheDocument();
  });

  it('shows sun icon (switch to light) in dark mode', async () => {
    mockTheme = 'dark';
    const { default: ThemeToggle } = await import('../components/ThemeToggle');
    render(<ThemeToggle />);
    const btn = screen.getByRole('button');
    expect(btn).toHaveAttribute('aria-label', 'Switch to light mode');
    expect(btn).toHaveAttribute('aria-pressed', 'true');
    expect(btn.querySelector('circle')).toBeInTheDocument();
  });

  it('calls toggleTheme on click', async () => {
    const { default: ThemeToggle } = await import('../components/ThemeToggle');
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole('button'));
    expect(mockToggleTheme).toHaveBeenCalledTimes(1);
  });

  it('has correct tooltip attribute', async () => {
    mockTheme = 'light';
    const { default: ThemeToggle } = await import('../components/ThemeToggle');
    render(<ThemeToggle />);
    expect(screen.getByRole('button')).toHaveAttribute('data-tooltip', 'Switch to dark mode');
  });
});

describe('Header', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders the mobile menu toggle', async () => {
    const { default: Header } = await import('../components/Header');
    render(<Header />);
    expect(screen.getByLabelText('Open navigation menu')).toBeInTheDocument();
  });

  it('renders the Refresh button', async () => {
    const { default: Header } = await import('../components/Header');
    render(<Header />);
    expect(screen.getByText('Refresh')).toBeInTheDocument();
  });

  it('calls onRefresh when Refresh is clicked', async () => {
    const onRefresh = vi.fn();
    const { default: Header } = await import('../components/Header');
    render(<Header onRefresh={onRefresh} />);
    fireEvent.click(screen.getByText('Refresh'));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('disables the Refresh button when isLoading is true', async () => {
    const { default: Header } = await import('../components/Header');
    render(<Header isLoading={true} />);
    const btn = screen.getByText('Refresh').closest('button')!;
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute('aria-label', 'Refreshing...');
  });

  it('shows aria-label "Refresh dashboard data" when not loading', async () => {
    const { default: Header } = await import('../components/Header');
    render(<Header isLoading={false} />);
    const btn = screen.getByText('Refresh').closest('button')!;
    expect(btn).toHaveAttribute('aria-label', 'Refresh dashboard data');
  });

  it('renders the mobile menu button', async () => {
    const { default: Header } = await import('../components/Header');
    render(<Header />);
    const menuBtn = screen.getByRole('button', { name: /open navigation menu/i });
    expect(menuBtn).toBeInTheDocument();
  });

  it('calls onToggleSidebar when mobile menu button is clicked', async () => {
    const onToggle = vi.fn();
    const { default: Header } = await import('../components/Header');
    render(<Header onToggleSidebar={onToggle} />);
    fireEvent.click(screen.getByRole('button', { name: /open navigation menu/i }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('shows close icon when sidebarOpen is true', async () => {
    const { default: Header } = await import('../components/Header');
    render(<Header sidebarOpen={true} />);
    const menuBtn = screen.getByRole('button', { name: /close navigation menu/i });
    expect(menuBtn).toBeInTheDocument();
    expect(menuBtn).toHaveAttribute('aria-expanded', 'true');
  });

  it('has a banner role', async () => {
    const { default: Header } = await import('../components/Header');
    render(<Header />);
    expect(screen.getByRole('banner')).toBeInTheDocument();
  });
});

describe('Sidebar', () => {
  beforeEach(() => vi.clearAllMocks());

  const NAV_LABELS = [
    'Overview',
    'Dependencies',
    'Risk Assessment',
    'SLO Burn Rate',
    'Incidents',
    'Deployments',
    'Settings',
  ];

  it('renders all nav items', async () => {
    const { default: Sidebar } = await import('../components/Sidebar');
    render(<Sidebar />);
    for (const label of NAV_LABELS) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('has navigation role', async () => {
    const { default: Sidebar } = await import('../components/Sidebar');
    render(<Sidebar />);
    expect(screen.getByRole('navigation', { name: /main navigation/i })).toBeInTheDocument();
  });

  it('renders the Incidents nav item with its link', async () => {
    const { default: Sidebar } = await import('../components/Sidebar');
    render(<Sidebar />);
    const incidentsLink = screen.getByText('Incidents').closest('a');
    expect(incidentsLink).toBeInTheDocument();
    expect(incidentsLink).toHaveAttribute('href', '/incidents');
  });

  it('renders the brand name', async () => {
    const { default: Sidebar } = await import('../components/Sidebar');
    render(<Sidebar />);
    expect(screen.getByText('ChangeTrace')).toBeInTheDocument();
  });

  it('renders user info in footer', async () => {
    const { default: Sidebar } = await import('../components/Sidebar');
    render(<Sidebar />);
    expect(screen.getByText('Platform Engineer')).toBeInTheDocument();
    expect(screen.getByText('Admin')).toBeInTheDocument();
  });

  it('applies open class when isOpen is true', async () => {
    const { default: Sidebar } = await import('../components/Sidebar');
    const { container } = render(<Sidebar isOpen={true} />);
    expect(container.querySelector('.sidebar.open')).toBeInTheDocument();
  });

  it('calls onClose when a nav link is clicked', async () => {
    const onClose = vi.fn();
    const { default: Sidebar } = await import('../components/Sidebar');
    render(<Sidebar onClose={onClose} />);
    fireEvent.click(screen.getByText('Overview'));
    expect(onClose).toHaveBeenCalled();
  });
});

describe('RiskScoreCard', () => {
  beforeEach(() => vi.clearAllMocks());

  const defaultProps = {
    service: 'payment-service',
    namespace: 'production',
    riskScore: 0.75,
    riskLevel: 'high' as const,
    factors: { deployment_frequency: 0.8, incident_rate: 0.6, change_complexity: 0.9 },
  };

  it('renders the service name', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} />);
    expect(screen.getByText('payment-service')).toBeInTheDocument();
  });

  it('renders the namespace when provided', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} />);
    expect(screen.getByText('production')).toBeInTheDocument();
  });

  it('renders the risk score percentage', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} />);
    expect(screen.getByText('75%')).toBeInTheDocument();
  });

  it('renders the risk level label', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} />);
    expect(screen.getByText('HIGH')).toBeInTheDocument();
  });

  it('renders all risk factors', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} />);
    expect(screen.getByText('Deployment Frequency')).toBeInTheDocument();
    expect(screen.getByText('Incident Rate')).toBeInTheDocument();
    expect(screen.getByText('Change Complexity')).toBeInTheDocument();
  });

  it('renders factor percentages', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} />);
    expect(screen.getByText('80%')).toBeInTheDocument();
    expect(screen.getByText('60%')).toBeInTheDocument();
    expect(screen.getByText('90%')).toBeInTheDocument();
  });

  it('renders progressbar with correct aria attributes', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} />);
    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '75');
    expect(bar).toHaveAttribute('aria-valuemin', '0');
    expect(bar).toHaveAttribute('aria-valuemax', '100');
  });

  it('shows loading skeleton when isLoading is true', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} isLoading={true} />);
    expect(screen.queryByText('payment-service')).not.toBeInTheDocument();
    expect(document.querySelector('.risk-score-card.skeleton-loading')).toBeInTheDocument();
  });

  it('calls onClick when clicked', async () => {
    const onClick = vi.fn();
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} onClick={onClick} />);
    fireEvent.click(screen.getByText('payment-service').closest('article')!);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders with role="button" when onClick is provided', async () => {
    const onClick = vi.fn();
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} onClick={onClick} />);
    const article = screen.getByText('payment-service').closest('article')!;
    expect(article).toHaveAttribute('role', 'button');
    expect(article).toHaveAttribute('tabindex', '0');
  });

  it('renders with role="article" when no onClick', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} />);
    const article = screen.getByText('payment-service').closest('article')!;
    expect(article).toHaveAttribute('role', 'article');
  });

  it('renders deployment info when provided', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(
      <RiskScoreCard
        {...defaultProps}
        lastDeployment="v2.3.1"
        lastDeploymentTime="2 hours ago"
      />
    );
    expect(screen.getByText('v2.3.1')).toBeInTheDocument();
    expect(screen.getByText('2 hours ago')).toBeInTheDocument();
  });

  it('renders risk level with different severities', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    const { unmount } = render(
      <RiskScoreCard {...defaultProps} riskLevel="critical" riskScore={0.95} />
    );
    expect(screen.getByText('CRITICAL')).toBeInTheDocument();
    expect(screen.getByText('95%')).toBeInTheDocument();
    unmount();

    render(<RiskScoreCard {...defaultProps} riskLevel="low" riskScore={0.15} />);
    expect(screen.getByText('LOW')).toBeInTheDocument();
    expect(screen.getByText('15%')).toBeInTheDocument();
  });

  it('renders threshold legend', async () => {
    const { default: RiskScoreCard } = await import('../components/RiskScoreCard');
    render(<RiskScoreCard {...defaultProps} />);
    expect(screen.getByText('Low < 30%')).toBeInTheDocument();
    expect(screen.getByText('Medium 30-70%')).toBeInTheDocument();
    expect(screen.getByText('High 70-90%')).toBeInTheDocument();
    expect(screen.getByText('Critical > 90%')).toBeInTheDocument();
  });
});

describe('IncidentTimeline', () => {
  const mockIncidents = [
    {
      incident_id: 'INC-001',
      title: 'Database connection pool exhausted',
      severity: 'sev1',
      status: 'open',
      affected_service: 'payment-service',
      detected_at: '2025-01-15T10:00:00Z',
    },
    {
      incident_id: 'INC-002',
      title: 'High latency on API gateway',
      severity: 'sev2',
      status: 'investigating',
      affected_service: 'api-gateway',
      detected_at: '2025-01-15T11:30:00Z',
    },
    {
      incident_id: 'INC-003',
      title: 'Disk space warning',
      severity: 'sev3',
      status: 'resolved',
      affected_service: 'log-collector',
      detected_at: '2025-01-15T09:00:00Z',
      resolved_at: '2025-01-15T09:45:00Z',
    },
    {
      incident_id: 'INC-004',
      title: 'SSL certificate expiring soon',
      severity: 'sev4',
      status: 'open',
      affected_service: 'payment-service',
      detected_at: '2025-01-15T08:00:00Z',
    },
  ];

  beforeEach(() => vi.clearAllMocks());

  it('renders all incidents', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    expect(screen.getByText('INC-001')).toBeInTheDocument();
    expect(screen.getByText('INC-002')).toBeInTheDocument();
    expect(screen.getByText('INC-003')).toBeInTheDocument();
    expect(screen.getByText('INC-004')).toBeInTheDocument();
  });

  it('renders incident titles', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    expect(screen.getByText('Database connection pool exhausted')).toBeInTheDocument();
    expect(screen.getByText('High latency on API gateway')).toBeInTheDocument();
  });

  it('renders the timeline title', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    expect(screen.getByText('Incident Timeline')).toBeInTheDocument();
  });

  it('shows total incident count in stats', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    const statsRegion = screen.getByRole('status', { hidden: true });
    expect(statsRegion).toBeInTheDocument();
  });

  it('renders severity filter dropdown', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    expect(screen.getByLabelText('Filter by severity')).toBeInTheDocument();
  });

  it('renders status filter dropdown', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    expect(screen.getByLabelText('Filter by status')).toBeInTheDocument();
  });

  it('renders search input', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    expect(screen.getByPlaceholderText('Search incidents...')).toBeInTheDocument();
  });

  it('filters by severity when selecting sev1', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    fireEvent.change(screen.getByLabelText('Filter by severity'), { target: { value: 'sev1' } });
    expect(screen.getByText('INC-001')).toBeInTheDocument();
    expect(screen.queryByText('INC-002')).not.toBeInTheDocument();
    expect(screen.queryByText('INC-003')).not.toBeInTheDocument();
  });

  it('filters by severity when selecting sev3', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    fireEvent.change(screen.getByLabelText('Filter by severity'), { target: { value: 'sev3' } });
    expect(screen.queryByText('INC-001')).not.toBeInTheDocument();
    expect(screen.getByText('INC-003')).toBeInTheDocument();
  });

  it('filters by status when selecting open', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'open' } });
    expect(screen.getByText('INC-001')).toBeInTheDocument();
    expect(screen.getByText('INC-004')).toBeInTheDocument();
    expect(screen.queryByText('INC-002')).not.toBeInTheDocument();
  });

  it('searches incidents by title', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    fireEvent.change(screen.getByPlaceholderText('Search incidents...'), {
      target: { value: 'Database' },
    });
    expect(screen.getByText('INC-001')).toBeInTheDocument();
    expect(screen.queryByText('INC-002')).not.toBeInTheDocument();
    expect(screen.queryByText('INC-003')).not.toBeInTheDocument();
  });

  it('searches incidents by incident ID', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    fireEvent.change(screen.getByPlaceholderText('Search incidents...'), {
      target: { value: 'INC-003' },
    });
    expect(screen.getByText('INC-003')).toBeInTheDocument();
    expect(screen.queryByText('INC-001')).not.toBeInTheDocument();
  });

  it('searches incidents by affected service', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    fireEvent.change(screen.getByPlaceholderText('Search incidents...'), {
      target: { value: 'payment-service' },
    });
    expect(screen.getByText('INC-001')).toBeInTheDocument();
    expect(screen.getByText('INC-004')).toBeInTheDocument();
    expect(screen.queryByText('INC-002')).not.toBeInTheDocument();
  });

  it('shows empty state when no incidents match filters', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    fireEvent.change(screen.getByLabelText('Filter by severity'), { target: { value: 'sev1' } });
    fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'resolved' } });
    expect(screen.getByText('No incidents match the current filters')).toBeInTheDocument();
  });

  it('calls onIncidentClick when an incident is clicked', async () => {
    const onIncidentClick = vi.fn();
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} onIncidentClick={onIncidentClick} />);
    fireEvent.click(screen.getByText('INC-001').closest('[role="listitem"]')!);
    expect(onIncidentClick).toHaveBeenCalledWith(mockIncidents[0]);
  });

  it('shows loading skeleton when isLoading is true', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={[]} isLoading={true} />);
    expect(document.querySelector('.incident-timeline.skeleton-loading')).toBeInTheDocument();
    expect(screen.queryByText('INC-001')).not.toBeInTheDocument();
  });

  it('highlights selected incident', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    const { container } = render(
      <IncidentTimeline incidents={mockIncidents} selectedIncidentId="INC-002" />
    );
    const selected = container.querySelector('.timeline-item.selected');
    expect(selected).toBeInTheDocument();
  });

  it('shows all incidents when "All Severities" is selected', async () => {
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={mockIncidents} />);
    fireEvent.change(screen.getByLabelText('Filter by severity'), { target: { value: 'all' } });
    expect(screen.getByText('INC-001')).toBeInTheDocument();
    expect(screen.getByText('INC-002')).toBeInTheDocument();
    expect(screen.getByText('INC-003')).toBeInTheDocument();
    expect(screen.getByText('INC-004')).toBeInTheDocument();
  });

  it('renders remediation action when present', async () => {
    const incidentsWithRemediation = [
      {
        ...mockIncidents[0],
        remediation_action: 'restart_connection_pool',
      },
    ];
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={incidentsWithRemediation} />);
    expect(screen.getByText('restart connection pool')).toBeInTheDocument();
  });

  it('renders root cause candidate when present', async () => {
    const incidentsWithRootCause = [
      {
        ...mockIncidents[0],
        root_cause_candidate: 'Memory leak in connection handler',
        confidence: 0.85,
      },
    ];
    const { default: IncidentTimeline } = await import('../components/IncidentTimeline');
    render(<IncidentTimeline incidents={incidentsWithRootCause} />);
    expect(screen.getByText('Memory leak in connection handler')).toBeInTheDocument();
    expect(screen.getByText('85% confidence')).toBeInTheDocument();
  });
});

describe('SLOBurnChart', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders empty state when data is empty array', async () => {
    const { default: SLOBurnChart } = await import('../components/SLOBurnChart');
    render(<SLOBurnChart data={[]} />);
    expect(screen.getByText('No SLO burn rate data available')).toBeInTheDocument();
    expect(screen.getByText('Data will appear here when SLOs are configured')).toBeInTheDocument();
  });

  it('renders empty state when data is undefined', async () => {
    const { default: SLOBurnChart } = await import('../components/SLOBurnChart');
    render(<SLOBurnChart data={undefined as any} />);
    expect(screen.getByText('No SLO burn rate data available')).toBeInTheDocument();
  });

  it('renders loading skeleton when isLoading is true', async () => {
    const { default: SLOBurnChart } = await import('../components/SLOBurnChart');
    render(<SLOBurnChart data={[]} isLoading={true} />);
    expect(document.querySelector('.slo-burn-chart.skeleton-loading')).toBeInTheDocument();
    expect(screen.queryByText('No SLO burn rate data available')).not.toBeInTheDocument();
  });

  it('renders chart with data', async () => {
    const chartData = [
      {
        timestamp: '2025-01-15T10:00:00Z',
        service: 'payment-service',
        slo_name: 'availability',
        target: 99.9,
        actual: 99.5,
        burn_rate: 1.2,
        error_budget_remaining: 75.0,
      },
      {
        timestamp: '2025-01-15T11:00:00Z',
        service: 'payment-service',
        slo_name: 'availability',
        target: 99.9,
        actual: 99.3,
        burn_rate: 1.5,
        error_budget_remaining: 60.0,
      },
    ];
    const { default: SLOBurnChart } = await import('../components/SLOBurnChart');
    render(<SLOBurnChart data={chartData} />);
    expect(screen.getByText('SLO Burn Rate')).toBeInTheDocument();
  });

  it('renders chart title with service name when provided', async () => {
    const chartData = [
      {
        timestamp: '2025-01-15T10:00:00Z',
        service: 'payment-service',
        slo_name: 'availability',
        target: 99.9,
        actual: 99.5,
        burn_rate: 1.2,
        error_budget_remaining: 75.0,
      },
    ];
    const { default: SLOBurnChart } = await import('../components/SLOBurnChart');
    render(<SLOBurnChart data={chartData} service="payment-service" sloName="availability" />);
    const chartTitle = document.querySelector('.chart-title');
    expect(chartTitle).toBeInTheDocument();
    expect(within(chartTitle as HTMLElement).getByText('payment-service')).toBeInTheDocument();
    expect(within(chartTitle as HTMLElement).getByText(/Burn Rate/)).toBeInTheDocument();
    expect(screen.getByText('Service Level Objective Monitoring')).toBeInTheDocument();
  });

  it('renders chart summary stats', async () => {
    const chartData = [
      {
        timestamp: '2025-01-15T11:00:00Z',
        service: 'payment-service',
        slo_name: 'availability',
        target: 99.9,
        actual: 99.5,
        burn_rate: 1.2,
        error_budget_remaining: 75.0,
      },
    ];
    const { default: SLOBurnChart } = await import('../components/SLOBurnChart');
    render(<SLOBurnChart data={chartData} />);
    expect(screen.getByText('Current Actual')).toBeInTheDocument();
    expect(screen.getByText('99.50%')).toBeInTheDocument();
    expect(screen.getByText('99.90%')).toBeInTheDocument();
    expect(screen.getByText('1.20x')).toBeInTheDocument();
    expect(screen.getByText('75.0%')).toBeInTheDocument();
    expect(screen.getAllByText('Target').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Burn Rate').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Error Budget').length).toBeGreaterThanOrEqual(1);
  });

  it('renders chart legend items', async () => {
    const chartData = [
      {
        timestamp: '2025-01-15T10:00:00Z',
        service: 'payment-service',
        slo_name: 'availability',
        target: 99.9,
        actual: 99.5,
        burn_rate: 1.2,
        error_budget_remaining: 75.0,
      },
    ];
    const { default: SLOBurnChart } = await import('../components/SLOBurnChart');
    render(<SLOBurnChart data={chartData} />);
    expect(screen.getByLabelText('Target SLO')).toBeInTheDocument();
    expect(screen.getByLabelText('Actual SLO')).toBeInTheDocument();
    expect(screen.queryByLabelText('Burn Rate')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Error Budget Remaining')).not.toBeInTheDocument();
  });

  it('shows empty state when filtered data is empty', async () => {
    const chartData = [
      {
        timestamp: '2025-01-15T10:00:00Z',
        service: 'payment-service',
        slo_name: 'availability',
        target: 99.9,
        actual: 99.5,
        burn_rate: 1.2,
        error_budget_remaining: 75.0,
      },
    ];
    const { default: SLOBurnChart } = await import('../components/SLOBurnChart');
    render(<SLOBurnChart data={chartData} service="non-existent-service" />);
    expect(screen.getByText('No data for selected filters')).toBeInTheDocument();
  });

  it('has correct aria-label on chart container', async () => {
    const chartData = [
      {
        timestamp: '2025-01-15T10:00:00Z',
        service: 'payment-service',
        slo_name: 'availability',
        target: 99.9,
        actual: 99.5,
        burn_rate: 1.2,
        error_budget_remaining: 75.0,
      },
    ];
    const { default: SLOBurnChart } = await import('../components/SLOBurnChart');
    render(<SLOBurnChart data={chartData} service="payment-service" />);
    expect(screen.getByRole('img', { name: /payment-service burn rate chart/i })).toBeInTheDocument();
  });
});

describe('Hook exports', () => {
  const EXPECTED_HOOKS = [
    'useDependencyGraph',
    'useBlastRadius',
    'useIncidents',
    'useIncidentDetail',
    'useUpdateIncidentStatus',
    'useSLOBurnRate',
    'useSLOStatus',
    'useRiskScores',
    'useRiskHistory',
    'useCorrelationAccuracy',
    'useCorrelationAccuracyHistory',
    'useChanges',
    'useHealth',
    'useReadiness',
    'useRefreshDashboard',
    'useLogin',
    'useRegister',
    'useAuthUser',
    'useUpdateMe',
    'useSourceUrls',
    'useUpdateSourceUrls',
    'useSourceConfigs',
    'useUpdateGithubSource',
    'useTestGithub',
    'useTestNativeSource',
    'useUpdateNativeSource',
    'useDeleteNativeSource',
    'useSourceHealthHistory',
    'useRotateApiKey',
    'useApiKey',
  ];

  it('all hooks are exported as functions', async () => {
    const hooks = await import('../api/hooks');
    for (const name of EXPECTED_HOOKS) {
      expect(typeof (hooks as any)[name]).toBe('function');
    }
  });

  it('exports the correct number of hooks', async () => {
    const hooks = await import('../api/hooks');
    const exportedNames = Object.keys(hooks).filter(
      (k) => typeof (hooks as any)[k] === 'function'
    );
    expect(exportedNames.length).toBe(EXPECTED_HOOKS.length);
  });
});

describe('API client exports', () => {
  it('all API modules exist and are objects', async () => {
    const mod = await import('../api/client');
    expect(mod.api).toBeDefined();
    expect(mod.graphApi).toBeDefined();
    expect(mod.incidentsApi).toBeDefined();
    expect(mod.sloApi).toBeDefined();
    expect(mod.riskApi).toBeDefined();
    expect(mod.correlationApi).toBeDefined();
    expect(mod.changesApi).toBeDefined();
    expect(mod.healthApi).toBeDefined();
  });

  it('api has standard HTTP methods', async () => {
    const { api } = await import('../api/client');
    expect(typeof api.get).toBe('function');
    expect(typeof api.post).toBe('function');
    expect(typeof api.put).toBe('function');
    expect(typeof api.delete).toBe('function');
  });

  it('graphApi has expected methods', async () => {
    const { graphApi } = await import('../api/client');
    expect(typeof graphApi.getDependencyGraph).toBe('function');
    expect(typeof graphApi.getBlastRadius).toBe('function');
  });

  it('incidentsApi has expected methods', async () => {
    const { incidentsApi } = await import('../api/client');
    expect(typeof incidentsApi.getIncidents).toBe('function');
    expect(typeof incidentsApi.getIncidentDetail).toBe('function');
  });

  it('sloApi has expected methods', async () => {
    const { sloApi } = await import('../api/client');
    expect(typeof sloApi.getBurnRate).toBe('function');
    expect(typeof sloApi.getStatus).toBe('function');
  });

  it('riskApi has expected methods', async () => {
    const { riskApi } = await import('../api/client');
    expect(typeof riskApi.getHistory).toBe('function');
    expect(typeof riskApi.getCurrent).toBe('function');
  });

  it('correlationApi has expected methods', async () => {
    const { correlationApi } = await import('../api/client');
    expect(typeof correlationApi.getAccuracy).toBe('function');
    expect(typeof correlationApi.getAccuracyHistory).toBe('function');
  });

  it('changesApi has expected methods', async () => {
    const { changesApi } = await import('../api/client');
    expect(typeof changesApi.getChanges).toBe('function');
  });

  it('healthApi has expected methods', async () => {
    const { healthApi } = await import('../api/client');
    expect(typeof healthApi.check).toBe('function');
    expect(typeof healthApi.ready).toBe('function');
  });
});
