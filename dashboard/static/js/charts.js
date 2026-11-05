/**
 * MLBFD - Dashboard Charting Core
 * Author: Chirag (@chirag4455)
 */

// Elegant Color Palettes matching CSS Variables
const CHART_THEME = {
    fontFamily: "'Inter', system-ui, sans-serif",
    gridColor: 'rgba(255, 255, 255, 0.05)',
    textColor: 'rgba(255, 255, 255, 0.6)',
    brandColor: '#3b82f6',
    successColor: '#10b981',
    warningColor: '#f59e0b',
    dangerColor: '#ef4444',
    infoColor: '#06b6d4',
};

// Apply Chart.js Defaults
if (typeof Chart !== 'undefined') {
    Chart.defaults.font.family = CHART_THEME.fontFamily;
    Chart.defaults.color = CHART_THEME.textColor;
}

// Chart Helpers
function createGradient(ctx, colorStart, colorEnd) {
    const gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, colorStart);
    gradient.addColorStop(1, colorEnd);
    return gradient;
}

// Generate customizable options object
function getChartOptions(showLegend = true, aspect = false) {
    return {
        responsive: true,
        maintainAspectRatio: aspect,
        plugins: {
            legend: {
                display: showLegend,
                labels: {
                    color: CHART_THEME.textColor,
                    font: { size: 12, weight: '500' },
                    boxWidth: 15,
                    usePointStyle: true
                }
            },
            tooltip: {
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                titleColor: '#fff',
                bodyColor: '#ccc',
                borderColor: 'rgba(255, 255, 255, 0.1)',
                borderWidth: 1,
                padding: 12,
                cornerRadius: 8,
                displayColors: true,
                usePointStyle: true
            }
        },
        scales: {
            x: {
                grid: { color: CHART_THEME.gridColor, drawBorder: false },
                ticks: { color: CHART_THEME.textColor, font: { size: 11 } }
            },
            y: {
                grid: { color: CHART_THEME.gridColor, drawBorder: false },
                ticks: { color: CHART_THEME.textColor, font: { size: 11 } }
            }
        }
    };
}
