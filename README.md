# LibreChat compatible code interpreter

A FastAPI-based code interpreter service that provides code execution and file management capabilities. This service is compatible with the LibreChat Code Interpreter API specification.

> [!NOTE]
> This project is mostly a proof of concept and is not intended to be used in production.   
> 
> For production ready solution and to support the amazing work of LibreChat maintainers use the [LibreChat Code Interpreter](https://code.librechat.ai/pricing).

## Features

- Easy deployment with single docker compose file
- Code execution in Docker container sandbox
- File upload and download
- Multi-user support
- RESTful API with OpenAPI documentation


## Usage


### Running the project

Run the project with docker compose using `docker compose -f compose.prod.yml up`

It's possible to overwrite the default environment variables defined in [./app/shared/config.py](./app/shared/config.py) by creating a `.env` file in the root directory.
By default the project will create two directories in the root directory: `./config` and `./uploads`.

`config` directory will hold the sqlite database and temp uploaded files.
`uploads` directory will hold the files uploaded by the users. All files uploaded by the users will be, by default, deleted after 24 hours.

### Configuring LibreChat

LibreChat is configured to use the code interpreter API by default.

To configure LibreChat to use the local code interpreter, set the following environment variables in LibreChat:

```ini
# LIBRECHAT_CODE_API_KEY=... currently not needed
LIBRECHAT_CODE_BASEURL=http(s)://host:port/v1/librechat # for local testing use to point to host IP http://host.docker.internal:8000/v1/librechat
```


## Development

### Installation

1. Install dependencies using uv:
```bash
uv sync --all-extras
source .venv/bin/activate
```

## Running the Application

1. Start the development server:
```bash
docker compose up
```

The API will be available at `http://localhost:8000`. The OpenAPI documentation can be accessed at `http://localhost:8000/docs`.


### Running tests

```bash
pytest
```

