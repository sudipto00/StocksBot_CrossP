# Contributing to StocksBot

First off, thank you for considering contributing to StocksBot! It's people like you that make StocksBot such a great tool.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Workflow](#development-workflow)
- [Style Guidelines](#style-guidelines)
- [Commit Messages](#commit-messages)
- [Pull Request Process](#pull-request-process)

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally
3. Set up your development environment following the [Development Guide](DEVELOPMENT.md)
4. Create a new branch for your feature or bugfix

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check the existing issues to avoid duplicates. When you create a bug report, include as many details as possible:

- Use a clear and descriptive title
- Describe the exact steps to reproduce the problem
- Provide specific examples to demonstrate the steps
- Describe the behavior you observed and what behavior you expected
- Include screenshots if relevant
- Include your environment details (OS, Python version, Node version, etc.)

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion:

- Use a clear and descriptive title
- Provide a detailed description of the suggested enhancement
- Explain why this enhancement would be useful
- List any alternative solutions you've considered

### Contributing Code

1. **Find an Issue**: Look for issues labeled `good first issue` or `help wanted`
2. **Discuss First**: For large changes, open an issue first to discuss your approach
3. **Follow the Workflow**: See the Development Workflow section below

## Development Workflow

### 1. Setup Your Environment

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/StocksBot_CrossP.git
cd StocksBot_CrossP

# Add upstream remote
git remote add upstream https://github.com/sudipto00/StocksBot_CrossP.git

# Install dependencies
npm run install:all

# Setup database
cd backend
alembic upgrade head
```

### 2. Create a Branch

```bash
# Update your local main branch
git checkout main
git pull upstream main

# Create a feature branch
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bugfix-name
```

### 3. Make Your Changes

- Write clean, readable code
- Follow the existing code style
- Add tests for new functionality
- Update documentation as needed
- Ensure all tests pass

### 4. Test Your Changes

**Backend Tests:**
```bash
cd backend
pytest tests/
```

**Frontend Tests:**
```bash
cd ui
npm run test
```

**Manual Testing:**
- Run the application and test your changes
- Test on different platforms if possible (Windows, macOS, Linux)

### 5. Commit Your Changes

Follow our [commit message guidelines](#commit-messages).

```bash
git add .
git commit -m "type: brief description"
```

### 6. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then go to GitHub and create a Pull Request.

## Style Guidelines

### Python Code Style

- Follow [PEP 8](https://pep8.org/) style guide
- Use type hints where appropriate
- Maximum line length: 100 characters
- Use meaningful variable and function names
- Add docstrings to classes and functions

Example:
```python
def calculate_moving_average(prices: list[float], period: int) -> float:
    """
    Calculate simple moving average for given prices.
    
    Args:
        prices: List of price values
        period: Number of periods for the average
        
    Returns:
        The moving average value
    """
    return sum(prices[-period:]) / period
```

### TypeScript/React Code Style

- Use functional components with hooks
- Use TypeScript for type safety
- Follow existing naming conventions
- Use meaningful component and variable names
- Keep components small and focused

Example:
```typescript
interface PositionCardProps {
  symbol: string;
  quantity: number;
  currentPrice: number;
}

export const PositionCard: React.FC<PositionCardProps> = ({
  symbol,
  quantity,
  currentPrice,
}) => {
  // Component implementation
};
```

### File Structure

- Keep files focused on a single responsibility
- Group related functionality together
- Use index files for clean imports
- Follow the existing directory structure

## Commit Messages

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification.

### Format

```
type(scope): subject

body (optional)

footer (optional)
```

### Types

- **feat**: A new feature
- **fix**: A bug fix
- **docs**: Documentation changes
- **style**: Code style changes (formatting, semicolons, etc.)
- **refactor**: Code refactoring without feature changes
- **test**: Adding or updating tests
- **chore**: Maintenance tasks, dependency updates

### Examples

```
feat(api): add endpoint for exporting trades to CSV

fix(ui): resolve strategy deletion confirmation dialog issue

docs: update README with new export functionality

test(storage): add tests for position repository
```

## Pull Request Process

1. **Update Documentation**: Ensure README, API docs, etc. are updated
2. **Add Tests**: Include tests for new functionality
3. **Pass All Checks**: Ensure all tests and linters pass
4. **Update Changelog**: Add an entry if applicable
5. **Request Review**: Request review from maintainers
6. **Address Feedback**: Respond to review comments promptly
7. **Squash Commits**: Maintainers may ask you to squash commits

### PR Title Format

Use the same format as commit messages:
```
type(scope): brief description
```

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
Describe the tests you ran and how to reproduce

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] Documentation updated
- [ ] Tests added/updated
- [ ] All tests passing
- [ ] No new warnings
```

## Questions?

Feel free to open an issue with your question or reach out to the maintainers.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

Thank you for contributing to StocksBot! 🚀
