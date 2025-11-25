FROM public.ecr.aws/lambda/python:3.13

# Copy calculator handler
COPY lambda_handler_calculator.py ${LAMBDA_TASK_ROOT}/

# Copy entrypoint script
COPY entrypoint.py ${LAMBDA_TASK_ROOT}/

# Set the entrypoint to our wrapper script
ENTRYPOINT ["python", "/var/task/entrypoint.py"]
