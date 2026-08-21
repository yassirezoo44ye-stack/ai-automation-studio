# Explicit package marker — makes `migrations` a regular (non-namespace) package.
# Required so that `from migrations.versions.app_builder_schema import upgrade`
# works correctly inside the Docker image even in edge cases where the parent
# directory's sys.path entry isn't picked up as a namespace package root.
