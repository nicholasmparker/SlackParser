#!/bin/bash
# Enhanced test runner for SlackParser
# Runs tests in Docker container with improved options

set -e  # Exit on error

# Default values
TEST_ENV="test_db"
VERBOSE="-v"
COVERAGE=""
MARKERS=""
TEST_PATH="app/tests/"

# Display help message
function show_help {
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  --help                 Show this help message"
    echo "  --coverage             Run tests with coverage report"
    echo "  --module MODULE        Run tests from specific module (e.g., test_parser)"
    echo "  --function FUNCTION    Run specific test function (e.g., test_parse_message)"
    echo "  --marker MARKER        Run tests with specific marker (e.g., asyncio)"
    echo "  --quiet                Run with minimal output"
    echo "  --verbose              Run with verbose output (default)"
    echo "  --xvs                  Run with extra verbose output"
    echo ""
    echo "Examples:"
    echo "  $0 --module test_end_to_end"
    echo "  $0 --coverage --marker asyncio"
    echo "  $0 --function test_parse_channel_metadata"
    exit 0
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help)
            show_help
            ;;
        --coverage)
            COVERAGE="--cov=app --cov-report=term --cov-report=html"
            shift
            ;;
        --module)
            TEST_PATH="app/tests/$2.py"
            shift 2
            ;;
        --function)
            MARKERS="-k $2"
            shift 2
            ;;
        --marker)
            MARKERS="-m $2"
            shift 2
            ;;
        --quiet)
            VERBOSE="-q"
            shift
            ;;
        --verbose)
            VERBOSE="-v"
            shift
            ;;
        --xvs)
            VERBOSE="-vvs"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            ;;
    esac
done

# Run the tests in Docker
echo "Running tests: docker-compose exec web pytest $TEST_PATH $VERBOSE $COVERAGE $MARKERS"
docker-compose exec web pytest $TEST_PATH $VERBOSE $COVERAGE $MARKERS
