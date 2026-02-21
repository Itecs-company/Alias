FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# Clear Vite cache to prevent stale dependency issues
RUN rm -rf node_modules/.vite

ENV VITE_BACKEND_URL=http://backend:8000
ENV VITE_API_BASE_URL=/api

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--force"]
