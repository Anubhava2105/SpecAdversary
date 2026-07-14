FROM node:22-alpine
WORKDIR /app
COPY package.json .
RUN npm install
RUN addgroup -S app && adduser -S app -G app
COPY --chown=app:app . .
USER app
EXPOSE 5174
CMD ["npm", "run", "dev", "--", "--port", "5174"]
