# Contributing to MindType

Thank you for your interest in contributing to MindType! This document provides guidelines for contributing.

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported in [Issues](https://github.com/Maxborland/mindtype-app/issues)
2. If not, create a new issue using the bug report template
3. Include as much detail as possible:
   - OS version (Windows 10/11, Linux distro, macOS version)
   - MindType version
   - Steps to reproduce
   - Expected vs actual behavior
   - Screenshots if applicable

### Suggesting Features

1. Check existing issues and discussions first
2. Create a feature request using the template
3. Explain the use case and why it would benefit users

### Code Contributions

#### Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/Maxborland/mindtype-app.git
cd mindtype-app

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or
.\venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

#### Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests: `pytest`
5. Commit with clear messages
6. Push to your fork
7. Open a Pull Request

#### Code Style

- Follow PEP 8 for Python code
- Use type hints where possible
- Write docstrings for public functions
- Keep functions focused and small
- Add tests for new functionality

#### Commit Messages

Use clear, descriptive commit messages:

```
feat: add support for MP4 file processing
fix: resolve crash when microphone disconnects
docs: update installation instructions
refactor: simplify transcription pipeline
```

## Development Guidelines

### Architecture

- `app/` - Main application code
- `app/ui/` - PyQt6 UI components
- `app/platform/` - Platform-specific code
- `app/licensing/` - License validation
- `tests/` - Test files

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test file
pytest tests/test_transcriber.py
```

### Building

See [README.md](README.md) for build instructions.

## Code of Conduct

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before contributing.

## Questions?

Feel free to open a discussion or issue if you have questions about contributing.

## License

By contributing, you agree that your contributions will be licensed under the AGPL-3.0 License.
