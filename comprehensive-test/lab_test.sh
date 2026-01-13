#!/bin/bash

# Comprehensive Test Orchestrator
# Runs all lab environments and generates consolidated report
# For TELE 6510 Lab - Northeastern University

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$REPO_ROOT/lab_results"

# Colors for output
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Print header
print_header() {
    echo -e "${BLUE}"
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║          TELE 6510 IoT Lab - Comprehensive Test Runner         ║"
    echo "║        Northeastern University - 2025                         ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Cleanup on exit
cleanup() {
    echo -e "${YELLOW}[INFO]${NC} Cleaning up..."
    # Kill any remaining background processes
    jobs -p | xargs -r kill 2>/dev/null || true
}

trap cleanup EXIT

# Run environment test
run_environment() {
    local env_name=$1
    local env_dir=$2
    
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}[START]${NC} Running $env_name..."
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    if [ ! -d "$env_dir" ]; then
        echo -e "${RED}[ERROR]${NC} Directory not found: $env_dir"
        return 1
    fi
    
    cd "$env_dir"
    
    if [ ! -f "test.sh" ]; then
        echo -e "${RED}[ERROR]${NC} test.sh not found in $env_dir"
        return 1
    fi
    
    chmod +x test.sh
    ./test.sh
    
    echo -e "${GREEN}[COMPLETE]${NC} $env_name testing finished"
    echo ""
    
    cd - > /dev/null
}

# Generate consolidated report
generate_report() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}[REPORT]${NC} Generating consolidated report..."
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    if [ ! -d "$RESULTS_DIR/summary" ]; then
        mkdir -p "$RESULTS_DIR/summary"
    fi
    
    local report_file="$RESULTS_DIR/summary/FULL_REPORT.txt"
    
    echo "TELE 6510 IoT Lab - Comprehensive Test Report" > "$report_file"
    echo "=============================================" >> "$report_file"
    echo "Generated: $(date '+%Y-%m-%d %H:%M:%S')" >> "$report_file"
    echo "" >> "$report_file"
    
    # Environment 1 Summary
    if [ -f "$RESULTS_DIR/summary/env1_summary.csv" ]; then
        echo "ENVIRONMENT 1: CoAP + HTTP" >> "$report_file"
        echo "--------------------------" >> "$report_file"
        echo "" >> "$report_file"
        cat "$RESULTS_DIR/summary/env1_summary.csv" >> "$report_file"
        echo "" >> "$report_file"
        echo "" >> "$report_file"
    fi
    
    # Environment 2 Summary
    if [ -f "$RESULTS_DIR/summary/env2_summary.csv" ]; then
        echo "ENVIRONMENT 2: CoAP + MQTT" >> "$report_file"
        echo "--------------------------" >> "$report_file"
        echo "" >> "$report_file"
        cat "$RESULTS_DIR/summary/env2_summary.csv" >> "$report_file"
        echo "" >> "$report_file"
    fi
    
    echo -e "${GREEN}[SUCCESS]${NC} Report saved to: $report_file"
}

# Display summary
display_summary() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}[SUMMARY]${NC} Test Results Location"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "Environment 1 Results: $RESULTS_DIR/env1/"
    echo "  - Captures: $RESULTS_DIR/env1/captures/"
    echo "  - Latencies: $RESULTS_DIR/env1/latencies/"
    echo ""
    echo "Environment 2 Results: $RESULTS_DIR/env2/"
    echo "  - Captures: $RESULTS_DIR/env2/captures/"
    echo "  - Latencies: $RESULTS_DIR/env2/latencies/"
    echo ""
    echo "Summary Tables: $RESULTS_DIR/summary/"
    echo ""
    
    if [ -f "$RESULTS_DIR/summary/env1_summary.csv" ]; then
        echo -e "${GREEN}Environment 1 Summary:${NC}"
        cat "$RESULTS_DIR/summary/env1_summary.csv"
        echo ""
    fi
    
    if [ -f "$RESULTS_DIR/summary/env2_summary.csv" ]; then
        echo -e "${GREEN}Environment 2 Summary:${NC}"
        cat "$RESULTS_DIR/summary/env2_summary.csv"
        echo ""
    fi
}

# Main execution
main() {
    print_header
    
    echo "This script will run comprehensive tests for both lab environments."
    echo "Each environment tests different protocol combinations."
    echo ""
    echo -e "${YELLOW}[WARNING]${NC} This process may take 30+ minutes depending on your system."
    echo "Press Enter to continue or Ctrl+C to cancel..."
    read -p ""
    
    # Check if environments exist
    if [ ! -d "$REPO_ROOT/environment-1-coap-http" ] || [ ! -d "$REPO_ROOT/environment-2-coap-mqtt" ]; then
        echo -e "${RED}[ERROR]${NC} Environment directories not found."
        exit 1
    fi
    
    # Run environments
    run_environment "Environment 1: CoAP + HTTP" "$REPO_ROOT/environment-1-coap-http"
    run_environment "Environment 2: CoAP + MQTT" "$REPO_ROOT/environment-2-coap-mqtt"
    
    # Generate report
    generate_report
    
    # Display summary
    display_summary
    
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                    ALL TESTS COMPLETED                         ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
}

main
