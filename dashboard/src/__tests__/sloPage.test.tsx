import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';

vi.mock('../components/SLOBurnChart.css', () => ({}));

vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(),
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

const mockUseQuery = vi.mocked((await import('@tanstack/react-query')).useQuery);

const SLO_STATUS = {
  services: [
    {
      name: 'payment-service',
      slos: [
        {
          name: 'availability',
          target: 99.9,
          current: 99.5,
          burn_rate: 1.2,
          error_budget_remaining: 75.0,
        },
      ],
    },
  ],
  updated_at: '2025-01-15T12:00:00Z',
};

const BURN_DATA = [
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

const mockUseQueryImpl = (options: { queryKey: unknown[] }) => {
  const key = options.queryKey as string[];
  if (key[0] === 'sloStatus') {
    return { data: SLO_STATUS, isLoading: false, isError: false, refetch: vi.fn() };
  }
  if (key[0] === 'sloBurnRate') {
    return { data: BURN_DATA, isLoading: false, isError: false, refetch: vi.fn() };
  }
  return { data: undefined, isLoading: false, isError: false, refetch: vi.fn() };
};

const lastBurnRateParams = () => {
  const calls = mockUseQuery.mock.calls.filter(([o]) => (o as any).queryKey?.[0] === 'sloBurnRate');
  return (calls[calls.length - 1]![0] as any).queryKey[1];
};

describe('SLO page time range dropdown', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseQuery.mockImplementation(mockUseQueryImpl as any);
  });

  it('renders the dropdown toggle showing the current range', async () => {
    const { default: SLO } = await import('../pages/SLO');
    render(<SLO />);
    const toggle = screen.getByRole('button', { name: /last 24h/i });
    expect(toggle).toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-haspopup', 'listbox');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('lists all range options when opened', async () => {
    const { default: SLO } = await import('../pages/SLO');
    render(<SLO />);
    fireEvent.click(screen.getByRole('button', { name: /last 24h/i }));

    const listbox = screen.getByRole('listbox', { name: /time range/i });
    expect(within(listbox).getByText('Last 15m')).toBeInTheDocument();
    expect(within(listbox).getByText('Last 1h')).toBeInTheDocument();
    expect(within(listbox).getByText('Last 3h')).toBeInTheDocument();
    expect(within(listbox).getByText('Last 6h')).toBeInTheDocument();
    expect(within(listbox).getByText('Last 12h')).toBeInTheDocument();
    expect(within(listbox).getByText('Last 24h')).toBeInTheDocument();
    expect(within(listbox).getByText('Last 7d')).toBeInTheDocument();
  });

  it('defaults to the 24h range (marked active)', async () => {
    const { default: SLO } = await import('../pages/SLO');
    render(<SLO />);
    fireEvent.click(screen.getByRole('button', { name: /last 24h/i }));
    const listbox = screen.getByRole('listbox', { name: /time range/i });
    const activeItem = within(listbox).getByRole('option', { selected: true });
    expect(activeItem).toHaveTextContent('Last 24h');
  });

  it('refetches burn rate with the selected range', async () => {
    const { default: SLO } = await import('../pages/SLO');
    render(<SLO />);
    fireEvent.click(screen.getByRole('button', { name: /last 24h/i }));
    fireEvent.click(screen.getByText('Last 1h'));

    const params = lastBurnRateParams();
    expect(params.hours).toBe(1);
    expect(params.interval_minutes).toBe(5);
  });

  it('supports the 15 minute range', async () => {
    const { default: SLO } = await import('../pages/SLO');
    render(<SLO />);
    fireEvent.click(screen.getByRole('button', { name: /last 24h/i }));
    fireEvent.click(screen.getByText('Last 15m'));

    const params = lastBurnRateParams();
    expect(params.hours).toBe(0.25);
    expect(params.interval_minutes).toBe(5);
  });

  it('switches to the 7 day range', async () => {
    const { default: SLO } = await import('../pages/SLO');
    render(<SLO />);
    fireEvent.click(screen.getByRole('button', { name: /last 24h/i }));
    fireEvent.click(screen.getByText('Last 7d'));

    const params = lastBurnRateParams();
    expect(params.hours).toBe(168);
    expect(params.interval_minutes).toBe(60);
  });

  it('closes the dropdown after selecting an option', async () => {
    const { default: SLO } = await import('../pages/SLO');
    render(<SLO />);
    fireEvent.click(screen.getByRole('button', { name: /last 24h/i }));
    fireEvent.click(screen.getByText('Last 1h'));
    expect(screen.queryByRole('listbox', { name: /time range/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /last 1h/i })).toBeInTheDocument();
  });

  it('groups SLO charts by type with a title above each group (latency first)', async () => {
    mockUseQuery.mockImplementation(((options: { queryKey: unknown[] }) => {
      const key = options.queryKey as string[];
      if (key[0] === 'sloStatus') {
        return {
          data: {
            services: [
              {
                name: 'payment-service',
                slos: [
                  { name: 'availability', target: 99.9, current: 99.5, burn_rate: 1.2, error_budget_remaining: 75.0 },
                  { name: 'latency_p99', target: 500, current: 25.5, burn_rate: 0.8, error_budget_remaining: 92.1 },
                ],
              },
            ],
            updated_at: '2025-01-15T12:00:00Z',
          },
          isLoading: false,
          isError: false,
          refetch: vi.fn(),
        };
      }
      if (key[0] === 'sloBurnRate') {
        return { data: [], isLoading: false, isError: false, refetch: vi.fn() };
      }
      return { data: undefined, isLoading: false, isError: false, refetch: vi.fn() };
    }) as any);
    const { default: SLO } = await import('../pages/SLO');
    const { container } = render(<SLO />);

    const titles = [...container.querySelectorAll('.slo-group-title')].map((h) => h.textContent || '');
    expect(titles).toEqual(['Latency P99', 'Availability']);

    const groups = [...container.querySelectorAll('.slo-group')];
    expect(groups.length).toBe(2);
    expect(groups[0]!.querySelector('.chart-title')?.textContent).toContain('payment-service');
    expect(groups[1]!.querySelector('.chart-title')?.textContent).toContain('payment-service');
  });
});
