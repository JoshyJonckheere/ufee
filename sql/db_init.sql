CREATE USER 'ufee-admin'@'localhost' IDENTIFIED BY 'adminpassword';
CREATE USER 'ufee-web'@'localhost' IDENTIFIED BY 'webpassword';


GRANT ALL PRIVILEGES ON project1.* to 'project1-admin'@'localhost' WITH GRANT OPTION;
GRANT SELECT, INSERT, UPDATE, DELETE ON project1.* TO 'project1-web'@'localhost';
FLUSH PRIVILEGES;