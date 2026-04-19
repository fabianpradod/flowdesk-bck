def assign_permissions(db, user, permissions):
    user.permissions = permissions
    db.commit()
    db.refresh(user)
    return user