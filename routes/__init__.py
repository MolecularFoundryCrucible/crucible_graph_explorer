def register_routes(app, auth, helpers=None):
    from .projects    import create_blueprint as projects_bp
    from .samples     import create_blueprint as samples_bp
    from .datasets    import create_blueprint as datasets_bp
    from .users       import create_blueprint as users_bp
    from .instruments import create_blueprint as instruments_bp
    from .graphs      import create_blueprint as graphs_bp
    from .search      import create_blueprint as search_bp
    from .chat        import create_blueprint as chat_bp
    from .hyperspec   import create_blueprint as hyperspec_bp

    for factory in [projects_bp, samples_bp, datasets_bp, users_bp,
                    instruments_bp, graphs_bp, search_bp, hyperspec_bp]:
        app.register_blueprint(factory(auth))
    app.register_blueprint(chat_bp(auth, helpers or {}))
