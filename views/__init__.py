def register_all(app, auth, helpers):
    from .datasets    import register_all as reg_datasets
    from .instruments import register_all as reg_instruments
    from .projects    import register_all as reg_projects
    reg_datasets(app, auth, helpers)
    reg_instruments(app, auth, helpers)
    reg_projects(app, auth, helpers)
