# Scheduling Agent

A powerful AI-powered scheduling assistant that helps you manage your calendar events using natural language. Built with Python and leveraging the TogetherAI API, this agent can create, modify, and delete calendar events through simple conversational commands.

## Features

- **Natural Language Processing**: Schedule events using everyday language
- **Google Calendar Integration**: Seamlessly manage your Google Calendar events
- **Smart Event Management**:
  - Create new events with automatic time parsing
  - Remove events using natural language commands
  - View daily schedules
  - Handle timezone-aware scheduling
  - Conflict detection for overlapping events
- **Interactive Interface**: Simple command-line interface for easy interaction

## Prerequisites

- Python 3.8 or higher
- Google Calendar API credentials
- TogetherAI API key

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd scheduling-agent
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
Create a `.env` file in the root directory with the following variables:
```
TOGETHER_API_KEY=your_together_api_key
CALENDAR_ID=your_google_calendar_id
```

4. Set up Google Calendar API:
   - Go to the [Google Cloud Console](https://console.cloud.google.com)
   - Create a new project
   - Enable the Google Calendar API
   - Create OAuth 2.0 credentials
   - Download the credentials and save as `credentials.json` in the project root

## Usage

1. Start the interactive agent:
```bash
python src/agent.py
```

2. Enter your scheduling commands in natural language. Examples:

### Creating Events
```
Task/Event: Schedule a meeting with John tomorrow at 2pm for 1 hour
Task/Event: Add workout session on Saturday from 9am to 10am
```

### Removing Events
```
Task/Event: remove meeting with John Saturday from 2 PM to 3 PM
Task/Event: delete workout session on Saturday
```

### Viewing Schedule
The agent will automatically show your schedule for the day after each operation.

## Features in Detail

### Event Creation
- Automatically parses dates and times from natural language
- Handles relative dates (today, tomorrow, next week)
- Supports various time formats (2pm, 14:00, 2:00 PM)
- Automatically detects and warns about scheduling conflicts

### Event Removal
- Remove events using natural language commands
- Supports multiple formats:
  - "remove meeting with John"
  - "delete workout session"
  - "cancel team meeting"
- Shows updated schedule after removal

### Timezone Handling
- All events are stored in America/Chicago timezone
- Automatic conversion for display and storage
- Consistent handling across all operations

### Error Handling
- Validates date and time formats
- Checks for scheduling conflicts
- Provides clear error messages
- Retries with more explicit prompts when needed

## Project Structure

```
scheduling-agent/
├── src/
│   ├── agent.py           # Main agent implementation
│   ├── tools/
│   │   └── calendar_tools.py  # Calendar operation tools
│   ├── models.py          # Data models
│   └── prompts.py         # System prompts
├── credentials.json       # Google API credentials
├── token.json            # OAuth token (generated)
├── .env                  # Environment variables
└── requirements.txt      # Project dependencies
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- TogetherAI for providing the LLM API
- Google Calendar API for calendar integration
- LangChain for the agent framework
